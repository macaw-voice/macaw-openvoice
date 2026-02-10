"""BatchAccumulator — acumula requests batch para despacho em grupo.

M8-05: Acumulacao de Requests para Batch Inference.

O BatchAccumulator agrupa requests BATCH por modelo, despachando-as como
lote apos ``accumulate_ms`` ou quando ``max_batch_size`` e atingido.
Requests REALTIME NAO passam pelo acumulador — sao enviadas diretamente.

O acumulador e componente do *scheduler*, nao do worker. O scheduler decide
QUANDO agrupar; o worker decide COMO processar o grupo (M8-06).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from Macaw.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from Macaw.scheduler.queue import ScheduledRequest

logger = get_logger("scheduler.batching")


class BatchAccumulator:
    """Acumula requests batch por tempo ou contagem antes de flush.

    Flush ocorre automaticamente em duas situacoes:
    1. Timer de ``accumulate_ms`` expira (flush com o que tem).
    2. ``max_batch_size`` e atingido (flush imediato).

    Requests canceladas sao removidas antes do flush.
    Todas as requests no batch devem ter o mesmo ``model_name``.

    Args:
        accumulate_ms: Tempo maximo de acumulacao antes de flush (ms).
        max_batch_size: Tamanho maximo do batch antes de flush imediato.
        on_flush: Callback async invocado com a lista de requests acumuladas.
    """

    def __init__(
        self,
        *,
        accumulate_ms: float = 50.0,
        max_batch_size: int = 8,
        on_flush: Callable[[list[ScheduledRequest]], Coroutine[object, object, None]],
    ) -> None:
        if accumulate_ms <= 0:
            msg = f"accumulate_ms must be positive, got {accumulate_ms}"
            raise ValueError(msg)
        if max_batch_size < 1:
            msg = f"max_batch_size must be >= 1, got {max_batch_size}"
            raise ValueError(msg)

        self._accumulate_s = accumulate_ms / 1000.0
        self._max_batch_size = max_batch_size
        self._on_flush = on_flush

        self._buffer: list[ScheduledRequest] = []
        self._model_name: str | None = None
        self._timer_handle: asyncio.TimerHandle | None = None
        self._flush_tasks: set[asyncio.Task[None]] = set()

    @property
    def pending_count(self) -> int:
        """Numero de requests no buffer aguardando flush."""
        return len(self._buffer)

    @property
    def model_name(self) -> str | None:
        """Modelo do batch atual, ou None se vazio."""
        return self._model_name

    def add(self, scheduled: ScheduledRequest) -> None:
        """Adiciona request ao batch atual.

        Se o batch esta vazio, define o ``model_name`` do batch.
        Se a request e para um modelo diferente, forca flush do batch
        atual antes de adicionar.

        Inicia timer de flush se este e o primeiro item.
        Se ``max_batch_size`` e atingido, forca flush imediato.

        Args:
            scheduled: Request a adicionar ao batch.

        Raises:
            RuntimeError: Se chamado sem event loop ativo.
        """
        request_model = scheduled.request.model_name

        # Se batch atual e para outro modelo, flush antes de adicionar
        if self._model_name is not None and self._model_name != request_model:
            logger.debug(
                "batch_model_mismatch_flush",
                current_model=self._model_name,
                new_model=request_model,
                flushing_count=len(self._buffer),
            )
            self._schedule_flush_now()

        # Primeiro item: define modelo e inicia timer
        if not self._buffer:
            self._model_name = request_model
            self._start_timer()

        self._buffer.append(scheduled)

        logger.debug(
            "batch_add",
            request_id=scheduled.request.request_id,
            model=request_model,
            batch_size=len(self._buffer),
        )

        # max_batch_size atingido: flush imediato
        if len(self._buffer) >= self._max_batch_size:
            logger.debug(
                "batch_max_size_flush",
                batch_size=len(self._buffer),
                max_batch_size=self._max_batch_size,
            )
            self._schedule_flush_now()

    def flush(self) -> list[ScheduledRequest]:
        """Retorna requests acumuladas e reseta o buffer.

        Remove requests canceladas antes de retornar.
        Cancela timer pendente.

        Returns:
            Lista de ScheduledRequests nao-canceladas (pode ser vazia).
        """
        self._cancel_timer()

        # Filtra requests canceladas
        batch = [s for s in self._buffer if not s.cancel_event.is_set()]
        cancelled_count = len(self._buffer) - len(batch)

        if cancelled_count > 0:
            logger.debug(
                "batch_flush_removed_cancelled",
                removed=cancelled_count,
                remaining=len(batch),
            )

        # Reset
        self._buffer.clear()
        self._model_name = None

        return batch

    def _start_timer(self) -> None:
        """Inicia timer de flush apos accumulate_ms."""
        self._cancel_timer()
        loop = asyncio.get_running_loop()
        self._timer_handle = loop.call_later(
            self._accumulate_s,
            self._on_timer_expired,
        )

    def _cancel_timer(self) -> None:
        """Cancela timer pendente se existir."""
        if self._timer_handle is not None:
            self._timer_handle.cancel()
            self._timer_handle = None

    def _on_timer_expired(self) -> None:
        """Callback do timer: executa flush e invoca on_flush."""
        self._timer_handle = None
        batch = self.flush()
        if batch:
            logger.info(
                "batch_timer_flush",
                batch_size=len(batch),
                model=batch[0].request.model_name,
            )
            # Agenda on_flush como task (callback do timer e sincrono)
            task = asyncio.create_task(self._on_flush(batch))
            self._flush_tasks.add(task)
            task.add_done_callback(self._flush_tasks.discard)

    def _schedule_flush_now(self) -> None:
        """Agenda flush imediato via call_soon (nao bloqueia add()).

        Necessario porque add() e sincrono mas on_flush e async.
        """
        batch = self.flush()
        if batch:
            task = asyncio.create_task(self._on_flush(batch))
            self._flush_tasks.add(task)
            task.add_done_callback(self._flush_tasks.discard)
