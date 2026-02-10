"""Worker Manager — gerencia lifecycle de workers STT/TTS como subprocessos.

Responsabilidades:
- Spawn de workers como subprocessos gRPC
- Health probing com backoff exponencial
- Monitoramento de processo (crash detection)
- Auto-restart com rate limiting
- Shutdown graceful
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum

from Macaw.logging import get_logger

logger = get_logger("worker.manager")

# Constants
MAX_CRASHES_IN_WINDOW = 3
CRASH_WINDOW_SECONDS = 60.0
HEALTH_PROBE_INITIAL_DELAY = 0.5
HEALTH_PROBE_MAX_DELAY = 5.0
HEALTH_PROBE_TIMEOUT = 30.0
STOP_GRACE_PERIOD = 5.0
MONITOR_INTERVAL = 1.0


class WorkerState(Enum):
    """Estado do worker no lifecycle."""

    STARTING = "starting"
    READY = "ready"
    BUSY = "busy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    CRASHED = "crashed"


@dataclass
class WorkerHandle:
    """Handle para um worker em execucao."""

    worker_id: str
    port: int
    model_name: str
    engine: str
    process: subprocess.Popen[bytes] | None = None
    state: WorkerState = WorkerState.STARTING
    crash_count: int = 0
    crash_timestamps: list[float] = field(default_factory=list)
    last_started_at: float = field(default_factory=time.monotonic)
    model_path: str = ""
    engine_config: dict[str, object] = field(default_factory=dict)
    worker_type: str = "stt"


class WorkerManager:
    """Gerencia lifecycle de workers gRPC como subprocessos.

    Cada worker e um processo separado rodando o servicer STT gRPC.
    O manager cuida de spawn, health check, crash detection e restart.
    """

    def __init__(self) -> None:
        self._workers: dict[str, WorkerHandle] = {}
        self._tasks: dict[str, list[asyncio.Task[None]]] = {}

    async def spawn_worker(
        self,
        model_name: str,
        port: int,
        engine: str,
        model_path: str,
        engine_config: dict[str, object],
        worker_type: str = "stt",
    ) -> WorkerHandle:
        """Inicia um novo worker como subprocess.

        Args:
            model_name: Nome do modelo (para identificacao).
            port: Porta gRPC para o worker escutar.
            engine: Nome da engine (ex: "faster-whisper", "kokoro").
            model_path: Caminho para os arquivos do modelo.
            engine_config: Configuracoes da engine.
            worker_type: Tipo do worker ("stt" ou "tts").

        Returns:
            WorkerHandle com informacoes do worker.
        """
        worker_id = f"{engine}-{port}"

        logger.info(
            "spawning_worker",
            worker_id=worker_id,
            port=port,
            engine=engine,
            worker_type=worker_type,
        )

        process = _spawn_worker_process(
            port, engine, model_path, engine_config, worker_type=worker_type
        )

        handle = WorkerHandle(
            worker_id=worker_id,
            port=port,
            model_name=model_name,
            engine=engine,
            process=process,
            state=WorkerState.STARTING,
            model_path=model_path,
            engine_config=engine_config,
            worker_type=worker_type,
        )

        self._workers[worker_id] = handle
        self._start_background_tasks(worker_id)

        return handle

    def _start_background_tasks(self, worker_id: str) -> None:
        """Inicia tasks de health probe e monitoramento para um worker."""
        health_task = asyncio.create_task(self._health_probe(worker_id))
        monitor_task = asyncio.create_task(self._monitor_worker(worker_id))
        self._tasks[worker_id] = [health_task, monitor_task]

    async def _cancel_background_tasks(self, worker_id: str) -> None:
        """Cancela e aguarda finalizacao das tasks de background de um worker."""
        tasks = self._tasks.pop(worker_id, [])
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_worker(self, worker_id: str) -> None:
        """Para um worker gracefully (SIGTERM, espera, SIGKILL se necessario).

        Args:
            worker_id: ID do worker.
        """
        handle = self._workers.get(worker_id)
        if handle is None:
            return

        handle.state = WorkerState.STOPPING
        logger.info("stopping_worker", worker_id=worker_id)

        await self._cancel_background_tasks(worker_id)

        process = handle.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(None, process.wait),
                    timeout=STOP_GRACE_PERIOD,
                )
            except TimeoutError:
                logger.warning("worker_force_kill", worker_id=worker_id)
                process.kill()
                await asyncio.get_running_loop().run_in_executor(None, process.wait)

        handle.state = WorkerState.STOPPED
        logger.info("worker_stopped", worker_id=worker_id)

    async def stop_all(self) -> None:
        """Para todos os workers em paralelo."""
        worker_ids = list(self._workers.keys())
        if worker_ids:
            await asyncio.gather(*(self.stop_worker(wid) for wid in worker_ids))

    def get_worker(self, worker_id: str) -> WorkerHandle | None:
        """Retorna handle do worker pelo ID."""
        return self._workers.get(worker_id)

    def get_ready_worker(self, model_name: str) -> WorkerHandle | None:
        """Retorna primeiro worker READY para um dado modelo."""
        for handle in self._workers.values():
            if handle.model_name == model_name and handle.state == WorkerState.READY:
                return handle
        return None

    async def _health_probe(self, worker_id: str) -> None:
        """Verifica saude do worker com backoff exponencial apos spawn.

        Transita de STARTING -> READY quando health retorna ok.
        """
        handle = self._workers.get(worker_id)
        if handle is None:
            return

        delay = HEALTH_PROBE_INITIAL_DELAY
        start = time.monotonic()

        while handle.state == WorkerState.STARTING:
            elapsed = time.monotonic() - start
            if elapsed > HEALTH_PROBE_TIMEOUT:
                logger.error("health_probe_timeout", worker_id=worker_id)
                handle.state = WorkerState.CRASHED
                return

            try:
                await asyncio.sleep(delay)
                result = await _check_worker_health(
                    handle.port, timeout=2.0, worker_type=handle.worker_type
                )
                if result.get("status") == "ok":
                    handle.state = WorkerState.READY
                    logger.info("worker_ready", worker_id=worker_id, elapsed_s=round(elapsed, 2))
                    return
            except asyncio.CancelledError:
                return
            except Exception:
                pass

            delay = min(delay * 2, HEALTH_PROBE_MAX_DELAY)

    async def _monitor_worker(self, worker_id: str) -> None:
        """Monitora processo do worker, detecta crashes."""
        handle = self._workers.get(worker_id)
        if handle is None:
            return

        try:
            while handle.state not in (WorkerState.STOPPING, WorkerState.STOPPED):
                await asyncio.sleep(MONITOR_INTERVAL)

                process = handle.process
                if process is None:
                    continue

                exit_code = process.poll()
                if exit_code is not None and handle.state not in (
                    WorkerState.STOPPING,
                    WorkerState.STOPPED,
                ):
                    stderr_output = ""
                    if process.stderr is not None:
                        with contextlib.suppress(Exception):
                            stderr_output = process.stderr.read().decode(errors="replace")[-2000:]
                    logger.error(
                        "worker_crashed",
                        worker_id=worker_id,
                        exit_code=exit_code,
                        stderr=stderr_output or "(empty)",
                    )
                    handle.state = WorkerState.CRASHED
                    await self._attempt_restart(worker_id)
                    return
        except asyncio.CancelledError:
            return

    async def _attempt_restart(self, worker_id: str) -> None:
        """Tenta reiniciar worker com rate limiting.

        Nao reinicia se exceder MAX_CRASHES_IN_WINDOW dentro de CRASH_WINDOW_SECONDS.
        """
        handle = self._workers.get(worker_id)
        if handle is None:
            return

        now = time.monotonic()
        handle.crash_count += 1
        handle.crash_timestamps.append(now)

        # Limpar timestamps fora da janela
        handle.crash_timestamps = [
            ts for ts in handle.crash_timestamps if now - ts < CRASH_WINDOW_SECONDS
        ]

        if len(handle.crash_timestamps) >= MAX_CRASHES_IN_WINDOW:
            logger.error(
                "worker_max_crashes_exceeded",
                worker_id=worker_id,
                crashes=handle.crash_count,
                window_seconds=CRASH_WINDOW_SECONDS,
            )
            handle.state = WorkerState.CRASHED
            return

        # Backoff baseado no numero de crashes recentes
        backoff = HEALTH_PROBE_INITIAL_DELAY * (2 ** len(handle.crash_timestamps))
        logger.info(
            "worker_restarting",
            worker_id=worker_id,
            backoff_s=backoff,
            crash_count=handle.crash_count,
        )

        await asyncio.sleep(backoff)

        process = _spawn_worker_process(
            handle.port,
            handle.engine,
            handle.model_path,
            handle.engine_config,
            worker_type=handle.worker_type,
        )

        handle.process = process
        handle.state = WorkerState.STARTING
        handle.last_started_at = time.monotonic()

        # Nao usar _cancel_background_tasks aqui — estamos executando DENTRO
        # de _monitor_worker, que e uma das tasks no dict. Cancelar a si mesmo
        # causaria CancelledError e _start_background_tasks nunca executaria.
        # As tasks antigas ja terminaram (health probe completou, monitor esta
        # prestes a retornar apos este metodo). Apenas substituir no dict.
        self._tasks.pop(worker_id, None)
        self._start_background_tasks(worker_id)


def _build_worker_cmd(
    port: int,
    engine: str,
    model_path: str,
    engine_config: dict[str, object],
    worker_type: str = "stt",
) -> list[str]:
    """Constroi comando CLI para iniciar worker como subprocess.

    Args:
        port: Porta gRPC para o worker escutar.
        engine: Nome da engine (ex: "faster-whisper", "kokoro").
        model_path: Caminho para os arquivos do modelo.
        engine_config: Configuracoes da engine.
        worker_type: Tipo do worker ("stt" ou "tts").

    Returns:
        Lista de argumentos para subprocess.Popen.
    """
    module = "Macaw.workers.tts" if worker_type == "tts" else "Macaw.workers.stt"
    cmd = [
        sys.executable,
        "-m",
        module,
        "--port",
        str(port),
        "--engine",
        engine,
        "--model-path",
        model_path,
    ]

    if worker_type == "tts":
        config_to_flag: dict[str, str] = {
            "device": "--device",
            "model_name": "--model-name",
        }
    else:
        config_to_flag = {
            "compute_type": "--compute-type",
            "device": "--device",
            "model_size": "--model-size",
            "beam_size": "--beam-size",
        }

    for config_key, cli_flag in config_to_flag.items():
        if config_key in engine_config:
            cmd.extend([cli_flag, str(engine_config[config_key])])

    return cmd


def _spawn_worker_process(
    port: int,
    engine: str,
    model_path: str,
    engine_config: dict[str, object],
    worker_type: str = "stt",
) -> subprocess.Popen[bytes]:
    """Cria subprocess do worker.

    Args:
        port: Porta gRPC para o worker escutar.
        engine: Nome da engine.
        model_path: Caminho para os arquivos do modelo.
        engine_config: Configuracoes da engine.
        worker_type: Tipo do worker ("stt" ou "tts").

    Returns:
        Popen handle do processo criado.
    """
    cmd = _build_worker_cmd(port, engine, model_path, engine_config, worker_type=worker_type)
    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


async def _check_worker_health(
    port: int, timeout: float = 2.0, worker_type: str = "stt"
) -> dict[str, str]:
    """Verifica health de um worker via gRPC Health RPC.

    Args:
        port: Porta gRPC do worker.
        timeout: Timeout em segundos.
        worker_type: Tipo do worker ("stt" ou "tts").

    Returns:
        Dict com status do worker.
    """
    import grpc.aio

    channel = grpc.aio.insecure_channel(f"localhost:{port}")
    try:
        if worker_type == "tts":
            from Macaw.proto import TTSHealthRequest, TTSWorkerStub

            tts_stub = TTSWorkerStub(channel)  # type: ignore[no-untyped-call]
            response = await asyncio.wait_for(
                tts_stub.Health(TTSHealthRequest()),
                timeout=timeout,
            )
        else:
            from Macaw.proto import HealthRequest
            from Macaw.proto.stt_worker_pb2_grpc import STTWorkerStub

            stt_stub = STTWorkerStub(channel)  # type: ignore[no-untyped-call]
            response = await asyncio.wait_for(
                stt_stub.Health(HealthRequest()),
                timeout=timeout,
            )
        return {
            "status": response.status,
            "model_name": response.model_name,
            "engine": response.engine,
        }
    finally:
        await channel.close()
