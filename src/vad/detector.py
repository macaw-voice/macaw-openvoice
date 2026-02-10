"""VAD Detector que orquestra EnergyPreFilter + SileroVADClassifier.

Coordena o pipeline de deteccao de atividade de voz em dois estagios:
1. EnergyPreFilter (rapido, ~0.1ms) descarta frames de silencio obvio
2. SileroVADClassifier (~2ms) classifica frames restantes como fala/silencio

Gerencia debounce (min speech/silence duration) e max speech duration,
emitindo eventos VADEvent (SPEECH_START, SPEECH_END) quando ocorrem
transicoes de estado confirmadas.

Custo total: ~0.1ms/frame quando energy pre-filter descarta, ~2ms/frame quando Silero e invocado.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING

from Macaw._types import VADSensitivity
from Macaw.logging import get_logger

if TYPE_CHECKING:
    import numpy as np

    from Macaw.vad.energy import EnergyPreFilter
    from Macaw.vad.silero import SileroVADClassifier

logger = get_logger("vad.detector")


class VADEventType(enum.Enum):
    """Tipo de evento VAD emitido pelo detector."""

    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"


@dataclass(frozen=True, slots=True)
class VADEvent:
    """Evento de transicao de estado do VAD.

    Emitido quando ocorre transicao confirmada entre fala e silencio
    (apos debounce). Inclui timestamp em milissegundos calculado
    a partir do total de samples processados.
    """

    type: VADEventType
    timestamp_ms: int


class VADDetector:
    """Detector de atividade de voz com debounce e max speech duration.

    Orquestra EnergyPreFilter (pre-filtro rapido) e SileroVADClassifier
    (classificador neural) para detectar transicoes fala/silencio com
    debounce configuravel.

    Comportamento:
        - EnergyPreFilter classifica como silencio -> Silero NAO e chamado
        - EnergyPreFilter classifica como nao-silencio -> Silero e chamado
        - Apos min_speech_duration_ms de fala consecutiva -> SPEECH_START
        - Apos min_silence_duration_ms de silencio consecutivo (durante fala) -> SPEECH_END
        - Apos max_speech_duration_ms de fala continua -> force SPEECH_END
    """

    def __init__(
        self,
        energy_pre_filter: EnergyPreFilter,
        silero_classifier: SileroVADClassifier,
        sensitivity: VADSensitivity = VADSensitivity.NORMAL,
        sample_rate: int = 16000,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 300,
        max_speech_duration_ms: int = 30_000,
    ) -> None:
        """Inicializa o detector.

        Args:
            energy_pre_filter: Pre-filtro de energia (descarta silencio obvio).
            silero_classifier: Classificador Silero VAD.
            sensitivity: Nivel de sensibilidade (informativo, thresholds sao
                         dos componentes injetados).
            sample_rate: Taxa de amostragem em Hz (deve ser 16000).
            min_speech_duration_ms: Duracao minima de fala consecutiva antes
                                    de emitir SPEECH_START (default: 250ms).
            min_silence_duration_ms: Duracao minima de silencio consecutivo
                                     antes de emitir SPEECH_END (default: 300ms).
            max_speech_duration_ms: Duracao maxima de fala continua antes de
                                    forcar SPEECH_END (default: 30000ms).
        """
        self._energy_pre_filter = energy_pre_filter
        self._silero_classifier = silero_classifier
        self._sensitivity = sensitivity
        self._sample_rate = sample_rate
        self._min_speech_duration_ms = min_speech_duration_ms
        self._min_silence_duration_ms = min_silence_duration_ms
        self._max_speech_duration_ms = max_speech_duration_ms

        # Estado interno
        self._samples_processed: int = 0
        self._is_speaking: bool = False
        self._consecutive_speech_samples: int = 0
        self._consecutive_silence_samples: int = 0
        self._speech_start_sample: int = 0  # sample onde speech comecou

    def process_frame(self, frame: np.ndarray) -> VADEvent | None:
        """Processa um frame de audio e retorna evento se houve transicao.

        Args:
            frame: Array numpy float32 mono 16kHz. Tamanho tipico: 1024 samples (64ms).

        Returns:
            VADEvent se houve transicao de estado (SPEECH_START ou SPEECH_END),
            None se nao houve transicao.
        """
        frame_samples = len(frame)

        # Classificar frame: silencio ou fala
        is_speech = self._classify_frame(frame)

        # Atualizar contadores de debounce (por total de samples, nao por frame count)
        if is_speech:
            self._consecutive_speech_samples += frame_samples
            self._consecutive_silence_samples = 0
        else:
            self._consecutive_silence_samples += frame_samples
            self._consecutive_speech_samples = 0

        event = self._check_transitions(frame_samples)

        self._samples_processed += frame_samples

        return event

    def _classify_frame(self, frame: np.ndarray) -> bool:
        """Classifica frame como fala (True) ou silencio (False).

        Usa energy pre-filter primeiro. Se pre-filter diz silencio,
        Silero NAO e chamado (otimizacao de performance).
        """
        if self._energy_pre_filter.is_silence(frame):
            return False

        return self._silero_classifier.is_speech(frame)

    def _check_transitions(self, frame_samples: int) -> VADEvent | None:
        """Verifica se debounce ou max duration triggeram uma transicao."""
        # Timestamp do momento ATUAL (apos processar este frame)
        current_timestamp_ms = self._compute_timestamp_ms(self._samples_processed + frame_samples)

        if not self._is_speaking:
            return self._check_speech_start(current_timestamp_ms, frame_samples)

        return self._check_speech_end(current_timestamp_ms, frame_samples)

    def _check_speech_start(self, timestamp_ms: int, frame_samples: int) -> VADEvent | None:
        """Verifica se debounce de fala foi atingido para emitir SPEECH_START."""
        consecutive_speech_ms = self._samples_to_ms(self._consecutive_speech_samples)

        if consecutive_speech_ms >= self._min_speech_duration_ms:
            self._is_speaking = True
            self._speech_start_sample = self._samples_processed + frame_samples
            self._consecutive_speech_samples = 0
            logger.debug(
                "VAD speech start",
                timestamp_ms=timestamp_ms,
                consecutive_ms=consecutive_speech_ms,
            )
            return VADEvent(type=VADEventType.SPEECH_START, timestamp_ms=timestamp_ms)

        return None

    def _check_speech_end(self, timestamp_ms: int, frame_samples: int) -> VADEvent | None:
        """Verifica se debounce de silencio ou max duration foram atingidos."""
        # Checar max speech duration primeiro
        speech_duration_ms = self._compute_timestamp_ms(
            self._samples_processed + frame_samples - self._speech_start_sample
        )

        if speech_duration_ms >= self._max_speech_duration_ms:
            self._is_speaking = False
            self._consecutive_speech_samples = 0
            self._consecutive_silence_samples = 0
            logger.info(
                "VAD force speech end (max duration)",
                timestamp_ms=timestamp_ms,
                speech_duration_ms=speech_duration_ms,
            )
            return VADEvent(type=VADEventType.SPEECH_END, timestamp_ms=timestamp_ms)

        # Checar debounce de silencio
        consecutive_silence_ms = self._samples_to_ms(self._consecutive_silence_samples)

        if consecutive_silence_ms >= self._min_silence_duration_ms:
            self._is_speaking = False
            self._consecutive_silence_samples = 0
            logger.debug(
                "VAD speech end",
                timestamp_ms=timestamp_ms,
                consecutive_silence_ms=consecutive_silence_ms,
            )
            return VADEvent(type=VADEventType.SPEECH_END, timestamp_ms=timestamp_ms)

        return None

    def _compute_timestamp_ms(self, total_samples: int) -> int:
        """Converte total de samples processados para milissegundos."""
        return int(total_samples * 1000 / self._sample_rate)

    def _samples_to_ms(self, total_samples: int) -> int:
        """Converte total de samples acumulados para milissegundos."""
        return int(total_samples * 1000 / self._sample_rate)

    def reset(self) -> None:
        """Reseta estado para nova sessao.

        Limpa contadores de debounce, estado de fala e samples processados.
        Tambem reseta estado interno do Silero (contexto temporal).
        """
        self._samples_processed = 0
        self._is_speaking = False
        self._consecutive_speech_samples = 0
        self._consecutive_silence_samples = 0
        self._speech_start_sample = 0
        self._silero_classifier.reset()

    @property
    def is_speaking(self) -> bool:
        """Se o detector esta atualmente no estado de fala."""
        return self._is_speaking
