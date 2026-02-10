"""Conversao entre tipos Macaw e mensagens protobuf gRPC.

Funcoes puras sem side effects — facilitam teste e reutilizacao.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from Macaw.proto import (
    HealthResponse,
    Segment,
    TranscribeFileResponse,
    TranscriptEvent,
    Word,
)

if TYPE_CHECKING:
    from Macaw._types import BatchResult, SegmentDetail, TranscriptSegment, WordTimestamp
    from Macaw.proto.stt_worker_pb2 import TranscribeFileRequest


def proto_request_to_transcribe_params(
    request: TranscribeFileRequest,
) -> dict[str, object]:
    """Converte TranscribeFileRequest gRPC em parametros para STTBackend.transcribe_file.

    Trata strings vazias como None (protobuf default para strings e string vazia).
    """
    language: str | None = request.language if request.language else None
    initial_prompt: str | None = request.initial_prompt if request.initial_prompt else None
    hot_words: list[str] | None = list(request.hot_words) if request.hot_words else None
    word_timestamps = "word" in list(request.timestamp_granularities)

    return {
        "audio_data": bytes(request.audio_data),
        "language": language,
        "initial_prompt": initial_prompt,
        "hot_words": hot_words,
        "temperature": request.temperature,
        "word_timestamps": word_timestamps,
    }


def segment_detail_to_proto(segment: SegmentDetail) -> Segment:
    """Converte SegmentDetail Macaw em Segment protobuf."""
    return Segment(
        id=segment.id,
        start=segment.start,
        end=segment.end,
        text=segment.text,
        avg_logprob=segment.avg_logprob,
        no_speech_prob=segment.no_speech_prob,
        compression_ratio=segment.compression_ratio,
    )


def word_timestamp_to_proto(word: WordTimestamp) -> Word:
    """Converte WordTimestamp Macaw em Word protobuf."""
    return Word(
        word=word.word,
        start=word.start,
        end=word.end,
        probability=word.probability if word.probability is not None else 0.0,
    )


def batch_result_to_proto_response(result: BatchResult) -> TranscribeFileResponse:
    """Converte BatchResult Macaw em TranscribeFileResponse protobuf."""
    segments = [segment_detail_to_proto(s) for s in result.segments]
    words = [word_timestamp_to_proto(w) for w in result.words] if result.words else []

    return TranscribeFileResponse(
        text=result.text,
        language=result.language,
        duration=result.duration,
        segments=segments,
        words=words,
    )


def health_dict_to_proto_response(
    health: dict[str, str],
    model_name: str,
    engine: str,
) -> HealthResponse:
    """Converte dict de health do backend em HealthResponse protobuf."""
    return HealthResponse(
        status=health.get("status", "unknown"),
        model_name=model_name,
        engine=engine,
    )


def transcript_segment_to_proto_event(
    segment: TranscriptSegment,
    session_id: str,
) -> TranscriptEvent:
    """Converte TranscriptSegment Macaw em TranscriptEvent protobuf.

    Usado pelo TranscribeStream para converter segmentos do backend
    em mensagens gRPC de streaming.
    """
    words = []
    if segment.words:
        words = [word_timestamp_to_proto(w) for w in segment.words]

    return TranscriptEvent(
        session_id=session_id,
        event_type="final" if segment.is_final else "partial",
        text=segment.text,
        segment_id=segment.segment_id,
        start_ms=segment.start_ms or 0,
        end_ms=segment.end_ms or 0,
        language=segment.language or "",
        confidence=segment.confidence or 0.0,
        words=words,
    )
