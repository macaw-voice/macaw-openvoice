"""Scheduler — roteia requests de transcricao para workers gRPC.

M8: Scheduler Avancado com PriorityQueue, dispatch loop assincrono,
pool de canais gRPC e graceful shutdown.

Streaming (WebSocket) NAO passa por este scheduler — usa StreamingGRPCClient
diretamente (M5). Este scheduler gerencia apenas requests batch.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Any

import grpc.aio

from Macaw.exceptions import WorkerCrashError, WorkerTimeoutError, WorkerUnavailableError
from Macaw.logging import get_logger
from Macaw.proto.stt_worker_pb2_grpc import STTWorkerStub
from Macaw.scheduler.batching import BatchAccumulator
from Macaw.scheduler.cancel import CancellationManager
from Macaw.scheduler.converters import build_proto_request, proto_response_to_batch_result
from Macaw.scheduler.latency import LatencyTracker
from Macaw.scheduler.metrics import (
    scheduler_aging_promotions_total,
    scheduler_batch_size,
    scheduler_grpc_duration_seconds,
    scheduler_queue_depth,
    scheduler_queue_wait_seconds,
    scheduler_requests_total,
)
from Macaw.scheduler.queue import RequestPriority, SchedulerQueue

if TYPE_CHECKING:
    from Macaw._types import BatchResult
    from Macaw.registry.registry import ModelRegistry
    from Macaw.scheduler.queue import ScheduledRequest
    from Macaw.server.models.requests import TranscribeRequest
    from Macaw.workers.manager import WorkerManager

logger = get_logger("scheduler")

# gRPC channel options — defaults do gRPC sao 4MB (insuficiente para audio de 25MB)
_GRPC_CHANNEL_OPTIONS = [
    ("grpc.max_send_message_length", 30 * 1024 * 1024),
    ("grpc.max_receive_message_length", 30 * 1024 * 1024),
    ("grpc.keepalive_time_ms", 30_000),
    ("grpc.keepalive_timeout_ms", 10_000),
    ("grpc.keepalive_permit_without_calls", 1),
]

# Timeout minimo para TranscribeFile (segundos)
_MIN_GRPC_TIMEOUT = 30.0

# Fator aplicado a duracao estimada do audio para calcular timeout
_TIMEOUT_FACTOR = 2.0

# Backoff quando nenhum worker esta disponivel (segundos)
_NO_WORKER_BACKOFF_S = 0.1

# Timeout para graceful shutdown (segundos)
_SHUTDOWN_TIMEOUT_S = 10.0


class Scheduler:
    """Roteia requests de transcricao para workers gRPC.

    M8: Scheduler com PriorityQueue, dispatch loop assincrono e pool de canais.

    Fluxo:
    1. ``transcribe(request)`` enfileira na PriorityQueue e aguarda future.
    2. ``_dispatch_loop()`` consome a fila, despacha para workers via gRPC.
    3. Resultado resolve o future, caller recebe ``BatchResult``.

    Lifecycle:
    - ``start()`` inicia o dispatch loop como background task.
    - ``stop()`` para o loop e aguarda requests em execucao (graceful, 10s timeout).
    """

    def __init__(
        self,
        worker_manager: WorkerManager,
        registry: ModelRegistry,
        *,
        aging_threshold_s: float = 30.0,
        batch_accumulate_ms: float = 50.0,
        batch_max_size: int = 8,
    ) -> None:
        self._worker_manager = worker_manager
        self._registry = registry
        self._queue = SchedulerQueue(aging_threshold_s=aging_threshold_s)
        self._channels: dict[str, grpc.aio.Channel] = {}
        self._dispatch_task: asyncio.Task[None] | None = None
        self._running = False
        self._in_flight: set[str] = set()
        self._in_flight_tasks: set[asyncio.Task[Any]] = set()
        self._cancellation = CancellationManager()
        self._batch_accumulator = BatchAccumulator(
            accumulate_ms=batch_accumulate_ms,
            max_batch_size=batch_max_size,
            on_flush=self._dispatch_batch,
        )
        self._latency = LatencyTracker()

    @property
    def queue(self) -> SchedulerQueue:
        """Acesso a fila para inspecao (metricas)."""
        return self._queue

    @property
    def cancellation(self) -> CancellationManager:
        """Acesso ao CancellationManager (para inspecao/metricas)."""
        return self._cancellation

    @property
    def batch_accumulator(self) -> BatchAccumulator:
        """Acesso ao BatchAccumulator (para inspecao/metricas)."""
        return self._batch_accumulator

    @property
    def latency(self) -> LatencyTracker:
        """Acesso ao LatencyTracker (para inspecao/metricas)."""
        return self._latency

    @property
    def running(self) -> bool:
        """True se o dispatch loop esta ativo."""
        return self._running

    def cancel(self, request_id: str) -> bool:
        """Cancela request na fila ou em execucao.

        Seta cancel_event e resolve future com CancelledError.
        Para requests em execucao, inicia propagacao gRPC ao worker como
        fire-and-forget task (nao bloqueia o caller).

        Idempotente: cancel de request inexistente/completada retorna False.

        Args:
            request_id: ID da request a cancelar.

        Returns:
            True se request foi encontrada e cancelada, False caso contrario.
        """
        # Captura worker_address ANTES de cancelar (cancel remove a entry)
        worker_address = self._cancellation.get_worker_address(request_id)
        channel = self._channels.get(worker_address) if worker_address else None

        # Captura prioridade para metrica ANTES de cancelar
        scheduled_for_metric = self._queue.get_scheduled(request_id)

        # Cancela via CancellationManager (seta event + resolve future)
        if not self._cancellation.cancel(request_id):
            return False

        # Remove do tracking da fila (para depth_by_priority correto)
        cancelled_in_queue = self._queue.cancel(request_id)

        # Atualiza queue depth se request estava na fila
        if (
            cancelled_in_queue
            and scheduler_queue_depth is not None
            and scheduled_for_metric is not None
        ):
            scheduler_queue_depth.labels(
                priority=scheduled_for_metric.priority.name,
            ).dec()

        # Remove do latency tracker (nao vai completar)
        self._latency.discard(request_id)

        # Se in-flight, propaga gRPC Cancel ao worker (fire-and-forget)
        if worker_address is not None:
            task = asyncio.create_task(
                self._cancellation.cancel_in_flight(request_id, worker_address, channel)
            )
            self._in_flight_tasks.add(task)
            task.add_done_callback(self._in_flight_tasks.discard)

        return True

    async def start(self) -> None:
        """Inicia o dispatch loop como background task.

        Idempotente: chamar start() quando ja esta rodando e no-op.
        """
        if self._running:
            return
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("scheduler_started")

    async def stop(self) -> None:
        """Para o dispatch loop e aguarda requests em execucao.

        Graceful shutdown com timeout de 10s. Requests nao concluidas
        apos o timeout sao canceladas.
        """
        if not self._running:
            return
        self._running = False

        # Flush batch accumulator (despacha requests pendentes)
        pending_batch = self._batch_accumulator.flush()
        if pending_batch:
            await self._dispatch_batch(pending_batch)

        # Sinaliza o dispatch loop para parar
        if self._dispatch_task is not None:
            self._dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dispatch_task
            self._dispatch_task = None

        # Aguarda requests em execucao (in-flight tasks) com timeout
        if self._in_flight_tasks:
            logger.info("scheduler_draining", in_flight=len(self._in_flight_tasks))
            _done, pending = await asyncio.wait(
                self._in_flight_tasks,
                timeout=_SHUTDOWN_TIMEOUT_S,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        # Fecha canais gRPC
        close_tasks = [channel.close() for channel in self._channels.values()]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        self._channels.clear()

        logger.info("scheduler_stopped")

    async def transcribe(self, request: TranscribeRequest) -> BatchResult:
        """Envia request ao worker e retorna resultado.

        Mantém a mesma assinatura externa de M3 para compatibilidade.

        Se o dispatch loop esta ativo (``start()`` chamado), enfileira na
        PriorityQueue e aguarda o future. Caso contrario, executa
        inline (compatibilidade com M3 e testes existentes).

        Raises:
            ModelNotFoundError: Modelo nao existe no registry.
            WorkerUnavailableError: Nenhum worker READY para o modelo.
            WorkerCrashError: Worker retornou erro irrecuperavel.
            WorkerTimeoutError: Worker nao respondeu dentro do timeout.
            asyncio.CancelledError: Request foi cancelada.
        """
        # Valida que modelo existe (levanta ModelNotFoundError se nao)
        self._registry.get_manifest(request.model_name)

        if not self._running:
            # Modo inline (M3 compat): executa diretamente sem fila
            return await self._transcribe_inline(request)

        # Modo M8: enfileira com prioridade BATCH e aguarda resultado
        future = await self.submit(request, RequestPriority.BATCH)
        return await future

    async def _transcribe_inline(self, request: TranscribeRequest) -> BatchResult:
        """Execucao inline sem fila (compatibilidade M3).

        Usado quando o dispatch loop nao esta ativo. Cria e fecha canal
        por request (comportamento identico ao M3 original).
        """
        worker = self._worker_manager.get_ready_worker(request.model_name)
        if worker is None:
            raise WorkerUnavailableError(request.model_name)

        logger.info(
            "transcribe_start",
            request_id=request.request_id,
            model=request.model_name,
            worker_id=worker.worker_id,
            audio_bytes=len(request.audio_data),
            task=request.task,
        )

        proto_request = build_proto_request(request)

        audio_duration_estimate = len(request.audio_data) / (16_000 * 2)
        timeout = max(_MIN_GRPC_TIMEOUT, audio_duration_estimate * _TIMEOUT_FACTOR)

        channel = grpc.aio.insecure_channel(
            f"localhost:{worker.port}",
            options=_GRPC_CHANNEL_OPTIONS,
        )
        try:
            stub = STTWorkerStub(channel)  # type: ignore[no-untyped-call]
            proto_response = await stub.TranscribeFile(
                proto_request,
                timeout=timeout,
            )
        except grpc.aio.AioRpcError as exc:
            _translate_grpc_error(exc, worker.worker_id, timeout)
            raise  # pragma: no cover — _translate_grpc_error sempre levanta
        finally:
            try:
                await channel.close()
            except Exception:
                logger.warning("channel_close_error", worker_id=worker.worker_id)

        result = proto_response_to_batch_result(proto_response)

        logger.info(
            "transcribe_done",
            request_id=request.request_id,
            text_length=len(result.text),
            segments=len(result.segments),
        )

        return result

    async def submit(
        self,
        request: TranscribeRequest,
        priority: RequestPriority = RequestPriority.BATCH,
    ) -> asyncio.Future[BatchResult]:
        """Enfileira request e retorna future para o caller aguardar.

        Diferente de ``transcribe()``, nao bloqueia ate o resultado.
        Permite que o caller faca cancel ou monitore progresso.
        Registra automaticamente no CancellationManager.
        """
        # Registra timestamp de enqueue
        self._latency.start(request.request_id)

        future = await self._queue.submit(request, priority)

        # Atualiza metrica de queue depth
        if scheduler_queue_depth is not None:
            scheduler_queue_depth.labels(priority=priority.name).inc()

        # Registra no CancellationManager para permitir cancel
        scheduled = self._queue.get_scheduled(request.request_id)
        if scheduled is not None:
            self._cancellation.register(
                request.request_id,
                scheduled.cancel_event,
                future,
            )

        return future

    async def _dispatch_loop(self) -> None:
        """Loop principal de despacho de requests.

        Consome a PriorityQueue e despacha para workers via gRPC.
        Roda como background task ate ``stop()`` ser chamado.
        """
        logger.info("dispatch_loop_started")
        try:
            while self._running:
                try:
                    scheduled = await asyncio.wait_for(
                        self._queue.dequeue(),
                        timeout=0.5,
                    )
                except TimeoutError:
                    continue

                # Registra timestamp de dequeue
                self._latency.dequeued(scheduled.request.request_id)

                # Atualiza queue depth (dec para a prioridade original)
                if scheduler_queue_depth is not None:
                    scheduler_queue_depth.labels(
                        priority=scheduled.priority.name,
                    ).dec()

                # Observa tempo na fila
                if scheduler_queue_wait_seconds is not None:
                    wait = time.monotonic() - scheduled.enqueued_at
                    scheduler_queue_wait_seconds.observe(wait)

                # Verifica aging (BATCH promovida para REALTIME)
                if self._queue.is_aged(scheduled):
                    if scheduler_aging_promotions_total is not None:
                        scheduler_aging_promotions_total.inc()
                    logger.info(
                        "dispatch_aged_promotion",
                        request_id=scheduled.request.request_id,
                    )

                # Verifica se request foi cancelada enquanto na fila
                if scheduled.cancel_event.is_set():
                    self._latency.discard(scheduled.request.request_id)
                    if scheduler_requests_total is not None:
                        scheduler_requests_total.labels(
                            priority=scheduled.priority.name,
                            status="cancelled",
                        ).inc()
                    logger.debug(
                        "dispatch_skip_cancelled",
                        request_id=scheduled.request.request_id,
                    )
                    continue

                # REALTIME: despacha imediatamente (sem batching)
                # BATCH: acumula no BatchAccumulator (flush por timer ou max_size)
                if scheduled.priority == RequestPriority.REALTIME:
                    task = asyncio.create_task(self._dispatch_request(scheduled))
                    self._in_flight_tasks.add(task)
                    task.add_done_callback(self._in_flight_tasks.discard)
                else:
                    self._batch_accumulator.add(scheduled)
        except asyncio.CancelledError:
            logger.info("dispatch_loop_cancelled")

    async def _dispatch_request(self, scheduled: ScheduledRequest) -> None:
        """Despacha uma request para o worker via gRPC.

        Se nenhum worker esta disponivel, re-enfileira com backoff.
        """
        request = scheduled.request
        future = scheduled.result_future

        # Encontra worker READY para o modelo
        worker = self._worker_manager.get_ready_worker(request.model_name)
        if worker is None:
            # Re-enfileira: cria nova ScheduledRequest preservando future e cancel_event
            await asyncio.sleep(_NO_WORKER_BACKOFF_S)

            # Verifica se foi cancelada durante backoff
            if scheduled.cancel_event.is_set():
                return

            # Re-enfileira na PriorityQueue
            await self._queue.resubmit(scheduled)
            logger.debug(
                "dispatch_requeue_no_worker",
                request_id=request.request_id,
                model=request.model_name,
            )
            return

        # Marca como in-flight
        address = f"localhost:{worker.port}"
        self._in_flight.add(request.request_id)
        self._cancellation.mark_in_flight(request.request_id, address)

        logger.info(
            "transcribe_start",
            request_id=request.request_id,
            model=request.model_name,
            worker_id=worker.worker_id,
            audio_bytes=len(request.audio_data),
            task=request.task,
        )

        grpc_start = time.monotonic()
        status = "ok"

        try:
            # Envia gRPC TranscribeFile ao worker
            proto_request = build_proto_request(request)

            # Timeout proporcional ao tamanho do audio
            audio_duration_estimate = len(request.audio_data) / (16_000 * 2)
            timeout = max(_MIN_GRPC_TIMEOUT, audio_duration_estimate * _TIMEOUT_FACTOR)

            channel = self._get_or_create_channel(address)
            stub = STTWorkerStub(channel)  # type: ignore[no-untyped-call]

            self._latency.grpc_started(request.request_id)
            proto_response = await stub.TranscribeFile(
                proto_request,
                timeout=timeout,
            )

            # Converte proto -> BatchResult
            result = proto_response_to_batch_result(proto_response)

            # Resolve future com resultado
            if future is not None and not future.done():
                future.set_result(result)

            logger.info(
                "transcribe_done",
                request_id=request.request_id,
                text_length=len(result.text),
                segments=len(result.segments),
            )

        except grpc.aio.AioRpcError as exc:
            status = "error"
            error = _make_domain_error(exc, worker.worker_id, timeout)
            if future is not None and not future.done():
                future.set_exception(error)

        except Exception as exc:
            status = "error"
            if future is not None and not future.done():
                future.set_exception(exc)

        finally:
            self._latency.complete(request.request_id)
            self._in_flight.discard(request.request_id)
            self._cancellation.unregister(request.request_id)

            # Observa metricas de gRPC e status
            grpc_elapsed = time.monotonic() - grpc_start
            if scheduler_grpc_duration_seconds is not None:
                scheduler_grpc_duration_seconds.observe(grpc_elapsed)
            if scheduler_requests_total is not None:
                scheduler_requests_total.labels(
                    priority=scheduled.priority.name,
                    status=status,
                ).inc()

    async def _dispatch_batch(self, batch: list[ScheduledRequest]) -> None:
        """Despacha um batch de requests em paralelo via asyncio.gather.

        Callback do BatchAccumulator. Todas as requests no batch sao enviadas
        em paralelo para o mesmo worker (HTTP/2 multiplexa via gRPC channel).
        Erro em uma request nao afeta as outras (return_exceptions=True no
        gather interno de _dispatch_request, que resolve futures individuais).
        """
        # Filtra canceladas entre add() e flush()
        active = [s for s in batch if not s.cancel_event.is_set()]
        if not active:
            return

        # Observa tamanho do batch
        if scheduler_batch_size is not None:
            scheduler_batch_size.observe(len(active))

        logger.info(
            "dispatch_batch",
            batch_size=len(active),
            model=active[0].request.model_name,
        )

        # Despacha todas em paralelo — cada _dispatch_request resolve seu future
        tasks = []
        for scheduled in active:
            task = asyncio.create_task(self._dispatch_request(scheduled))
            self._in_flight_tasks.add(task)
            task.add_done_callback(self._in_flight_tasks.discard)
            tasks.append(task)

        # Aguarda todas completarem (erros ja resolvidos nos futures individuais)
        await asyncio.gather(*tasks, return_exceptions=True)

    def _get_or_create_channel(self, address: str) -> grpc.aio.Channel:
        """Retorna canal gRPC para o address, criando se necessario."""
        channel = self._channels.get(address)
        if channel is None:
            channel = grpc.aio.insecure_channel(
                address,
                options=_GRPC_CHANNEL_OPTIONS,
            )
            self._channels[address] = channel
        return channel

    async def close_channel(self, address: str) -> None:
        """Fecha e remove canal gRPC para um address especifico.

        Usado quando um worker morre e o canal deve ser descartado.
        """
        channel = self._channels.pop(address, None)
        if channel is not None:
            try:
                await channel.close()
            except Exception:
                logger.warning("channel_close_error", address=address)


def _make_domain_error(
    exc: grpc.aio.AioRpcError,
    worker_id: str,
    timeout: float,
) -> WorkerCrashError | WorkerTimeoutError:
    """Traduz erros gRPC em exceptions de dominio do Macaw."""
    code = exc.code()

    if code == grpc.StatusCode.DEADLINE_EXCEEDED:
        return WorkerTimeoutError(worker_id, timeout)

    if code == grpc.StatusCode.UNAVAILABLE:
        return WorkerCrashError(worker_id)

    if code == grpc.StatusCode.CANCELLED:
        return WorkerCrashError(worker_id)

    # Demais erros gRPC → WorkerCrashError generico
    logger.error(
        "grpc_error",
        worker_id=worker_id,
        grpc_code=code.name if code else "UNKNOWN",
        grpc_details=exc.details(),
    )
    return WorkerCrashError(worker_id)


# Backward compat: re-export for existing code that imports _translate_grpc_error
def _translate_grpc_error(
    exc: grpc.aio.AioRpcError,
    worker_id: str,
    timeout: float,
) -> None:
    """Traduz erros gRPC em exceptions de dominio do Macaw.

    Sempre levanta — nunca retorna normalmente.
    Mantido para compatibilidade retroativa com testes existentes.
    """
    raise _make_domain_error(exc, worker_id, timeout) from exc
