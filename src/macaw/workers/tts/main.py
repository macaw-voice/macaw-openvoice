"""Entry point for the TTS worker as a gRPC subprocess.

Usage:
    python -m macaw.workers.tts --port 50052 --engine kokoro \
        --model-path /models/kokoro-v1
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from typing import TYPE_CHECKING

import grpc.aio

from macaw.logging import configure_logging, get_logger
from macaw.proto import add_TTSWorkerServicer_to_server
from macaw.workers.tts.servicer import TTSWorkerServicer

if TYPE_CHECKING:
    from macaw.workers.tts.interface import TTSBackend

logger = get_logger("worker.tts.main")

STOP_GRACE_PERIOD = 5.0


def _create_backend(engine: str) -> TTSBackend:
    """Create a TTSBackend instance based on the engine name.

    Raises:
        ValueError: If the engine is not supported.
    """
    if engine == "kokoro":
        from macaw.workers.tts.kokoro import KokoroBackend

        return KokoroBackend()

    if engine == "qwen3-tts":
        from macaw.workers.tts.qwen3 import Qwen3TTSBackend

        return Qwen3TTSBackend()

    msg = f"Engine TTS nao suportada: {engine}"
    raise ValueError(msg)


async def serve(
    port: int,
    engine: str,
    model_path: str,
    engine_config: dict[str, object],
) -> None:
    """Start the gRPC server for the TTS worker.

    Args:
        port: Port to listen on.
        engine: Engine name (e.g., "kokoro").
        model_path: Path to model files.
        engine_config: Engine configuration (device, etc).
    """
    backend = _create_backend(engine)

    logger.info("loading_model", engine=engine, model_path=model_path)
    await backend.load(model_path, engine_config)
    logger.info("model_loaded", engine=engine)

    await _warmup_backend(backend)

    model_name = str(engine_config.get("model_name", "unknown"))
    servicer = TTSWorkerServicer(
        backend=backend,
        model_name=model_name,
        engine=engine,
    )

    server = grpc.aio.server()
    add_TTSWorkerServicer_to_server(servicer, server)  # type: ignore[no-untyped-call]
    listen_addr = f"[::]:{port}"
    server.add_insecure_port(listen_addr)

    loop = asyncio.get_running_loop()
    shutting_down = False
    shutdown_task: asyncio.Task[None] | None = None

    async def _shutdown() -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        logger.info("shutdown_start", grace_period=STOP_GRACE_PERIOD)
        await server.stop(STOP_GRACE_PERIOD)
        await backend.unload()
        logger.info("shutdown_complete")

    def _signal_handler() -> None:
        nonlocal shutdown_task
        shutdown_task = asyncio.ensure_future(_shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    await server.start()
    logger.info("worker_started", port=port, engine=engine)

    await server.wait_for_termination()


async def _warmup_backend(backend: TTSBackend) -> None:
    """Run a dummy synthesis to warm up GPU caches and JIT.

    First real request would otherwise bear the cost of kernel compilation,
    memory allocation, and cache priming. Synthesizing a short text takes
    ~100-300ms but saves that latency from the first user request.
    """
    try:
        # synthesize() is an async generator in concrete backends, but the
        # ABC declares it as async def -> AsyncIterator (coroutine), causing
        # a mypy mismatch. At runtime, it returns an async iterable directly.
        async for _ in backend.synthesize("warmup"):  # type: ignore[attr-defined]
            break  # First chunk is enough to prime the pipeline
        logger.info("warmup_complete")
    except Exception as exc:
        logger.warning("warmup_failed", error=str(exc))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Macaw TTS Worker (gRPC)")
    parser.add_argument("--port", type=int, default=50052, help="gRPC port (default: 50052)")
    parser.add_argument(
        "--engine", type=str, default="kokoro", help="Engine TTS (default: kokoro)"
    )
    parser.add_argument("--model-path", type=str, required=True, help="Model path")
    parser.add_argument(
        "--engine-config",
        type=str,
        default="{}",
        help="Engine config as JSON string",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the TTS worker."""
    import json

    configure_logging()
    args = parse_args(argv)

    engine_config: dict[str, object] = json.loads(args.engine_config)

    try:
        asyncio.run(
            serve(
                port=args.port,
                engine=args.engine,
                model_path=args.model_path,
                engine_config=engine_config,
            )
        )
    except KeyboardInterrupt:
        logger.info("worker_interrupted")
        sys.exit(0)


if __name__ == "__main__":
    main()
