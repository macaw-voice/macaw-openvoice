"""Tipos fundamentais do Macaw OpenVoice.

Este modulo define enums, dataclasses e type aliases que sao usados
por todos os componentes do runtime. Alteracoes aqui impactam o sistema inteiro.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class STTArchitecture(Enum):
    """Arquitetura de modelo STT.

    Determina como o runtime adapta o pipeline de streaming:
    - ENCODER_DECODER: acumula windows, LocalAgreement para partials (ex: Whisper)
    - CTC: frame-by-frame, partials nativos (ex: WeNet CTC)
    - STREAMING_NATIVE: streaming verdadeiro, engine gerencia estado (ex: Paraformer)
    """

    ENCODER_DECODER = "encoder-decoder"
    CTC = "ctc"
    STREAMING_NATIVE = "streaming-native"


class ModelType(Enum):
    """Tipo de modelo no registry."""

    STT = "stt"
    TTS = "tts"


class SessionState(Enum):
    """Estado de uma sessao de streaming STT.

    Transicoes validas:
        INIT -> ACTIVE (primeiro audio com fala)
        INIT -> CLOSED (timeout 30s sem audio)
        ACTIVE -> SILENCE (VAD detecta silencio)
        SILENCE -> ACTIVE (VAD detecta fala)
        SILENCE -> HOLD (timeout 30s sem fala)
        HOLD -> ACTIVE (VAD detecta fala)
        HOLD -> CLOSING (timeout 5min)
        CLOSING -> CLOSED (flush completo ou timeout 2s)
        Qualquer -> CLOSED (erro irrecuperavel)
    """

    INIT = "init"
    ACTIVE = "active"
    SILENCE = "silence"
    HOLD = "hold"
    CLOSING = "closing"
    CLOSED = "closed"


class VADSensitivity(Enum):
    """Nivel de sensibilidade do VAD.

    Ajusta threshold do Silero VAD e energy pre-filter conjuntamente.
    """

    HIGH = "high"  # threshold=0.3, energy=-50dBFS (sussurro, banking)
    NORMAL = "normal"  # threshold=0.5, energy=-40dBFS (conversacao normal)
    LOW = "low"  # threshold=0.7, energy=-30dBFS (ambiente ruidoso)


class ResponseFormat(Enum):
    """Formato de resposta da API de transcricao."""

    JSON = "json"
    VERBOSE_JSON = "verbose_json"
    TEXT = "text"
    SRT = "srt"
    VTT = "vtt"


@dataclass(frozen=True, slots=True)
class WordTimestamp:
    """Timestamp de uma palavra individual."""

    word: str
    start: float
    end: float
    probability: float | None = None


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """Segmento de transcricao (partial ou final).

    Emitido pelo worker via gRPC e propagado ao cliente via WebSocket.
    """

    text: str
    is_final: bool
    segment_id: int
    start_ms: int | None = None
    end_ms: int | None = None
    language: str | None = None
    confidence: float | None = None
    words: tuple[WordTimestamp, ...] | None = None


@dataclass(frozen=True, slots=True)
class SegmentDetail:
    """Detalhes de um segmento no formato verbose_json."""

    id: int
    start: float
    end: float
    text: str
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    compression_ratio: float = 0.0


@dataclass(frozen=True, slots=True)
class BatchResult:
    """Resultado de transcricao batch (arquivo completo)."""

    text: str
    language: str
    duration: float
    segments: tuple[SegmentDetail, ...]
    words: tuple[WordTimestamp, ...] | None = None


@dataclass(frozen=True, slots=True)
class EngineCapabilities:
    """Capabilities reportadas pela engine STT em runtime.

    Pode diferir do manifesto (Macaw.yaml) se a engine descobrir
    capabilities adicionais apos load.
    """

    supports_hot_words: bool = False
    supports_initial_prompt: bool = False
    supports_batch: bool = False
    supports_word_timestamps: bool = False
    max_concurrent_sessions: int = 1


# --- TTS ---


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    """Informacoes sobre uma voz disponivel no backend TTS."""

    voice_id: str
    name: str
    language: str
    gender: str | None = None


@dataclass(frozen=True, slots=True)
class TTSSpeechResult:
    """Resultado de sintese TTS (audio completo).

    Usado pelo endpoint REST POST /v1/audio/speech.
    Para streaming, o TTSBackend.synthesize() retorna AsyncIterator[bytes].
    """

    audio_data: bytes
    sample_rate: int
    duration: float
    voice: str
