"""Conversao entre tipos Macaw e mensagens protobuf gRPC para TTS.

Funcoes puras sem side effects -- facilitam teste e reutilizacao.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from Macaw.proto.tts_worker_pb2 import (
    HealthResponse,
    SynthesizeChunk,
)

if TYPE_CHECKING:
    from Macaw.proto.tts_worker_pb2 import SynthesizeRequest


@dataclass(frozen=True, slots=True)
class SynthesizeParams:
    """Parametros tipados extraidos de SynthesizeRequest."""

    text: str
    voice: str
    sample_rate: int
    speed: float


def proto_request_to_synthesize_params(
    request: SynthesizeRequest,
) -> SynthesizeParams:
    """Converte SynthesizeRequest gRPC em parametros para TTSBackend.synthesize.

    Trata strings vazias como defaults (protobuf default para strings e string vazia).
    """
    voice: str = request.voice if request.voice else "default"
    sample_rate: int = request.sample_rate if request.sample_rate > 0 else 24000
    speed: float = request.speed if request.speed > 0.0 else 1.0

    return SynthesizeParams(
        text=request.text,
        voice=voice,
        sample_rate=sample_rate,
        speed=speed,
    )


def audio_chunk_to_proto(
    audio_data: bytes,
    is_last: bool,
    duration: float,
) -> SynthesizeChunk:
    """Converte chunk de audio em SynthesizeChunk protobuf."""
    return SynthesizeChunk(
        audio_data=audio_data,
        is_last=is_last,
        duration=duration,
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
