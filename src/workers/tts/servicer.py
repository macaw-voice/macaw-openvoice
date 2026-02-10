"""gRPC servicer para worker TTS.

Implementa o servico TTSWorker definido em tts_worker.proto.
Delega sintese ao TTSBackend injetado.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import grpc

from Macaw.logging import get_logger
from Macaw.workers.tts.converters import (
    audio_chunk_to_proto,
    health_dict_to_proto_response,
    proto_request_to_synthesize_params,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from Macaw.proto.tts_worker_pb2 import (
        HealthRequest,
        HealthResponse,
        SynthesizeChunk,
        SynthesizeRequest,
    )
    from Macaw.workers.tts.interface import TTSBackend

from Macaw.proto.tts_worker_pb2_grpc import TTSWorkerServicer as _BaseServicer

logger = get_logger("worker.tts.servicer")


class TTSWorkerServicer(_BaseServicer):
    """Implementacao do servico gRPC TTSWorker.

    Recebe requests gRPC, delega ao TTSBackend, retorna respostas proto.
    Synthesize e server-streaming: texto entra, chunks de audio saem.
    """

    def __init__(
        self,
        backend: TTSBackend,
        model_name: str,
        engine: str,
    ) -> None:
        self._backend = backend
        self._model_name = model_name
        self._engine = engine

    async def Synthesize(  # noqa: N802  # type: ignore[override]
        self,
        request: SynthesizeRequest,
        context: grpc.aio.ServicerContext[SynthesizeRequest, SynthesizeChunk],
    ) -> AsyncIterator[SynthesizeChunk]:
        """Sintese de voz via server-streaming.

        Recebe SynthesizeRequest com texto, delega ao TTSBackend.synthesize(),
        e yield SynthesizeChunk com audio PCM a medida que a engine sintetiza.
        """
        params = proto_request_to_synthesize_params(request)
        request_id = request.request_id
        text = params.text

        if not text.strip():
            logger.warning("synthesize_empty_text", request_id=request_id)
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Text must not be empty",
            )
            return  # pragma: no cover

        logger.info(
            "synthesize_start",
            request_id=request_id,
            voice=params.voice,
            text_length=len(text),
        )

        try:
            # synthesize() pode ser:
            # 1. Um async generator (usa yield) — retorna AsyncGenerator diretamente
            # 2. Uma coroutine async que retorna AsyncIterator — precisa de await
            # Usamos a mesma heuristica do STT: tentamos async for diretamente,
            # e se nao funcionar (coroutine), fazemos await primeiro.
            result = self._backend.synthesize(
                text=text,
                voice=params.voice,
                sample_rate=params.sample_rate,
                speed=params.speed,
            )

            # Se e uma coroutine (async def sem yield), await para obter o iterator
            stream: AsyncIterator[bytes]
            if inspect.iscoroutine(result):
                stream = await result
            else:
                stream = result  # type: ignore[assignment]

            accumulated_duration = 0.0
            chunk_count = 0

            async for audio_chunk in stream:
                if context.cancelled():
                    logger.info("synthesize_cancelled", request_id=request_id)
                    return

                chunk_count += 1
                # Estimar duracao do chunk: bytes / (sample_rate * 2 bytes por sample)
                chunk_duration = (
                    len(audio_chunk) / (params.sample_rate * 2) if params.sample_rate > 0 else 0.0
                )
                accumulated_duration += chunk_duration

                yield audio_chunk_to_proto(
                    audio_data=audio_chunk,
                    is_last=False,
                    duration=accumulated_duration,
                )

            # Enviar chunk final vazio sinalizando fim do stream
            yield audio_chunk_to_proto(
                audio_data=b"",
                is_last=True,
                duration=accumulated_duration,
            )

        except Exception as exc:
            logger.error(
                "synthesize_error",
                request_id=request_id,
                error=str(exc),
            )
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))
            return  # pragma: no cover

        logger.info(
            "synthesize_done",
            request_id=request_id,
            chunks=chunk_count,
            duration=accumulated_duration,
        )

    async def Health(  # noqa: N802  # type: ignore[override]
        self,
        request: HealthRequest,
        context: grpc.aio.ServicerContext[HealthRequest, HealthResponse],
    ) -> HealthResponse:
        """Health check do worker TTS."""
        health = await self._backend.health()
        return health_dict_to_proto_response(health, self._model_name, self._engine)
