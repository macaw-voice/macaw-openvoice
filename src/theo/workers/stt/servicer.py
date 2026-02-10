"""gRPC servicer para worker STT.

Implementa o servico STTWorker definido em stt_worker.proto.
Delega transcricao ao STTBackend injetado.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import grpc

from Macaw.logging import get_logger
from Macaw.proto.stt_worker_pb2 import (
    CancelResponse,
    TranscribeFileResponse,
    TranscriptEvent,
)
from Macaw.workers.stt.converters import (
    batch_result_to_proto_response,
    health_dict_to_proto_response,
    proto_request_to_transcribe_params,
    transcript_segment_to_proto_event,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from Macaw.proto.stt_worker_pb2 import (
        AudioFrame,
        CancelRequest,
        HealthRequest,
        TranscribeFileRequest,
    )
    from Macaw.workers.stt.interface import STTBackend

from Macaw.proto.stt_worker_pb2_grpc import STTWorkerServicer as _BaseServicer

logger = get_logger("worker.stt.servicer")


class STTWorkerServicer(_BaseServicer):
    """Implementacao do servico gRPC STTWorker.

    Recebe requests gRPC, delega ao STTBackend, retorna respostas proto.
    """

    def __init__(
        self,
        backend: STTBackend,
        model_name: str,
        engine: str,
        *,
        max_concurrent: int = 1,
    ) -> None:
        self._backend = backend
        self._model_name = model_name
        self._engine = engine
        self._max_concurrent = max(1, max_concurrent)
        self._inference_semaphore = asyncio.Semaphore(self._max_concurrent)
        self._cancel_lock = threading.Lock()
        self._cancelled_requests: set[str] = set()
        self._current_request_id: str | None = None

    def is_cancelled(self, request_id: str) -> bool:
        """Verifica se uma request foi cancelada.

        Thread-safe — pode ser chamado de executor threads durante inference.
        """
        with self._cancel_lock:
            return request_id in self._cancelled_requests

    async def TranscribeFile(  # noqa: N802  # type: ignore[override]
        self,
        request: TranscribeFileRequest,
        context: grpc.aio.ServicerContext[TranscribeFileRequest, TranscribeFileResponse],
    ) -> TranscribeFileResponse:
        """Transcricao batch de arquivo de audio.

        Usa semaphore para limitar concorrencia de inference no worker.
        Multiplas requests podem chegar via asyncio.gather() do scheduler
        (M8-06 batch dispatch). O semaphore garante que no maximo
        ``max_concurrent`` inferencias rodam em paralelo.
        """
        params = proto_request_to_transcribe_params(request)
        request_id = request.request_id

        with self._cancel_lock:
            self._current_request_id = request_id
            self._cancelled_requests.discard(request_id)

        logger.info(
            "transcribe_file_start",
            request_id=request_id,
            language=params.get("language"),
            audio_bytes=len(request.audio_data),
        )

        try:
            # Verifica cancelamento antes de adquirir semaphore
            if self.is_cancelled(request_id):
                logger.info("transcribe_file_cancelled_before_start", request_id=request_id)
                await context.abort(grpc.StatusCode.CANCELLED, "Request cancelled")
                return TranscribeFileResponse()  # pragma: no cover

            async with self._inference_semaphore:
                # Verifica cancelamento apos adquirir semaphore (pode ter esperado)
                if self.is_cancelled(request_id):
                    logger.info(
                        "transcribe_file_cancelled_after_semaphore",
                        request_id=request_id,
                    )
                    await context.abort(grpc.StatusCode.CANCELLED, "Request cancelled")
                    return TranscribeFileResponse()  # pragma: no cover

                result = await self._backend.transcribe_file(**params)  # type: ignore[arg-type]

            # Verifica cancelamento apos inference
            if self.is_cancelled(request_id):
                logger.info("transcribe_file_cancelled_after_inference", request_id=request_id)
                await context.abort(grpc.StatusCode.CANCELLED, "Request cancelled")
                return TranscribeFileResponse()  # pragma: no cover
        except Exception as exc:
            logger.error("transcribe_file_error", request_id=request_id, error=str(exc))
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))
            return TranscribeFileResponse()  # pragma: no cover — unreachable em gRPC real
        finally:
            with self._cancel_lock:
                self._current_request_id = None
                self._cancelled_requests.discard(request_id)

        logger.info(
            "transcribe_file_done",
            request_id=request_id,
            text_length=len(result.text),
            segments=len(result.segments),
        )

        return batch_result_to_proto_response(result)

    async def TranscribeStream(  # noqa: N802  # type: ignore[override]
        self,
        request_iterator: AsyncIterator[AudioFrame],
        context: grpc.aio.ServicerContext[AudioFrame, TranscriptEvent],
    ) -> AsyncIterator[TranscriptEvent]:
        """Transcricao STT em streaming bidirecional.

        Recebe stream de AudioFrames, delega ao backend via transcribe_stream,
        e retorna stream de TranscriptEvents.

        Metadados (session_id, initial_prompt, hot_words) sao extraidos do
        primeiro AudioFrame antes de iniciar o backend.
        """
        # Ler primeiro frame para extrair metadados da sessao
        first_frame: AudioFrame | None = None
        async for frame in request_iterator:
            first_frame = frame
            break

        if first_frame is None:
            # Stream vazio — nenhum frame recebido
            return

        session_id = first_frame.session_id
        initial_prompt: str | None = (
            first_frame.initial_prompt if first_frame.initial_prompt else None
        )
        hot_words: list[str] | None = (
            list(first_frame.hot_words) if first_frame.hot_words else None
        )

        # Se o primeiro frame ja sinaliza fim, nao ha audio para processar
        if first_frame.is_last:
            logger.info("transcribe_stream_empty", session_id=session_id)
            return

        async def audio_chunk_generator() -> AsyncIterator[bytes]:
            """Extrai PCM bytes do stream de AudioFrames.

            Emite os dados do primeiro frame (ja lido) e depois consome
            o restante do request_iterator.
            """
            # Emitir dados do primeiro frame
            yield bytes(first_frame.data)

            # Consumir frames restantes
            async for frame in request_iterator:
                if context.cancelled():
                    return
                if frame.is_last:
                    return
                yield bytes(frame.data)

        logger.info("transcribe_stream_start", session_id=session_id)

        try:
            # transcribe_stream e implementado como async generator em todos
            # os backends (usa yield), entao retorna AsyncGenerator diretamente.
            # mypy interpreta a assinatura ABC como Coroutine -> AsyncIterator,
            # mas na pratica o resultado e iteravel sem await.
            stream = self._backend.transcribe_stream(
                audio_chunks=audio_chunk_generator(),
                language=None,
                initial_prompt=initial_prompt,
                hot_words=hot_words,
            )
            async for segment in stream:  # type: ignore[attr-defined]
                if context.cancelled():
                    logger.info("transcribe_stream_cancelled", session_id=session_id)
                    return
                event = transcript_segment_to_proto_event(segment, session_id)
                yield event
        except Exception as exc:
            logger.error(
                "transcribe_stream_error",
                session_id=session_id,
                error=str(exc),
            )
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))
            return  # pragma: no cover — unreachable em gRPC real

        logger.info("transcribe_stream_done", session_id=session_id)

    async def Cancel(  # noqa: N802  # type: ignore[override]
        self,
        request: CancelRequest,
        context: grpc.aio.ServicerContext[CancelRequest, CancelResponse],
    ) -> CancelResponse:
        """Cancelamento cooperativo de request batch em execucao.

        Seta flag interno que e verificado entre segmentos de inference.
        O cancelamento e cooperative — nao interrompe CUDA kernels em execucao.

        Para streaming, o cancel continua via stream break (gRPC call.cancel()).
        """
        request_id = request.request_id

        with self._cancel_lock:
            self._cancelled_requests.add(request_id)
            is_current = self._current_request_id == request_id

        logger.info(
            "cancel_received",
            request_id=request_id,
            is_current_request=is_current,
        )

        return CancelResponse(acknowledged=True)

    async def Health(  # noqa: N802  # type: ignore[override]
        self,
        request: HealthRequest,
        context: grpc.aio.ServicerContext[HealthRequest, object],
    ) -> object:
        """Health check do worker."""
        health = await self._backend.health()
        return health_dict_to_proto_response(health, self._model_name, self._engine)
