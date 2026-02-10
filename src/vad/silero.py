"""Classificador de Voice Activity Detection usando Silero VAD.

Encapsula o modelo Silero VAD com lazy-loading e sensitivity levels
configuraveis. Retorna probabilidade de fala por frame.

Debounce (min speech/silence duration) NAO e responsabilidade desta classe
-- e tratado pelo VADDetector (camada acima).

Custo: ~2ms/frame em CPU.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Any

from Macaw._types import VADSensitivity

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

logger = logging.getLogger(__name__)

# Mapeamento de sensibilidade para threshold de probabilidade de fala.
# HIGH = detecta fala suave (sussurro), LOW = requer fala clara.
_THRESHOLDS: dict[VADSensitivity, float] = {
    VADSensitivity.HIGH: 0.3,
    VADSensitivity.NORMAL: 0.5,
    VADSensitivity.LOW: 0.7,
}

# Sample rate esperado pelo Silero VAD.
_EXPECTED_SAMPLE_RATE = 16000


class SileroVADClassifier:
    """Classificador de Voice Activity Detection usando Silero VAD.

    Lazy-loads o modelo na primeira chamada a get_speech_probability().
    Suporta PyTorch (torch.jit) como backend de inferencia.

    O classificador retorna probabilidade de fala para cada frame.
    Debounce (min speech/silence duration) NAO e responsabilidade desta classe
    -- e tratado pelo VADDetector.
    """

    def __init__(
        self,
        sensitivity: VADSensitivity = VADSensitivity.NORMAL,
        sample_rate: int = _EXPECTED_SAMPLE_RATE,
    ) -> None:
        """Inicializa o classificador.

        Args:
            sensitivity: Nivel de sensibilidade (ajusta threshold).
            sample_rate: Sample rate esperado (deve ser 16000).

        Raises:
            ValueError: Se sample_rate nao for 16000.
        """
        if sample_rate != _EXPECTED_SAMPLE_RATE:
            msg = (
                f"Silero VAD requer sample rate {_EXPECTED_SAMPLE_RATE}Hz, "
                f"recebido {sample_rate}Hz. Aplique resample antes."
            )
            raise ValueError(msg)

        self._sensitivity = sensitivity
        self._sample_rate = sample_rate
        self._threshold = _THRESHOLDS[sensitivity]
        self._model: object | None = None
        self._model_loaded = False
        self._to_tensor: Callable[[Any], Any] | None = None
        self._load_lock = threading.Lock()

    @property
    def threshold(self) -> float:
        """Threshold atual de probabilidade de fala."""
        return self._threshold

    @property
    def sensitivity(self) -> VADSensitivity:
        """Nivel de sensibilidade atual."""
        return self._sensitivity

    def set_sensitivity(self, sensitivity: VADSensitivity) -> None:
        """Atualiza a sensibilidade (e threshold correspondente).

        Args:
            sensitivity: Novo nivel de sensibilidade.
        """
        self._sensitivity = sensitivity
        self._threshold = _THRESHOLDS[sensitivity]

    async def preload(self) -> None:
        """Pre-carrega o modelo Silero VAD em thread separada.

        Evita bloquear o event loop asyncio durante o download/carregamento
        do modelo na primeira chamada. Chamar antes de iniciar o streaming.

        Raises:
            ImportError: Se torch nao esta instalado.
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._ensure_model_loaded)

    def _ensure_model_loaded(self) -> None:
        """Lazy-loads o modelo Silero VAD (thread-safe).

        Tenta carregar via torch.hub. Se torch nao esta disponivel,
        levanta ImportError com instrucoes de instalacao.

        Usa threading.Lock para garantir que o modelo e carregado
        uma unica vez mesmo com chamadas concorrentes.

        Raises:
            ImportError: Se torch nao esta instalado.
        """
        if self._model_loaded:
            return

        with self._load_lock:
            # Double-check apos adquirir lock
            if self._model_loaded:
                return

            try:
                import torch

                model, _utils = torch.hub.load(
                    repo_or_dir="snakers4/silero-vad",
                    model="silero_vad",
                    force_reload=False,
                )
                self._model = model
                self._to_tensor = torch.from_numpy
                self._model_loaded = True
                logger.info("Silero VAD carregado via PyTorch")
            except ImportError:
                msg = "Silero VAD requer torch. Instale com: pip install torch"
                raise ImportError(msg) from None

    def get_speech_probability(self, frame: np.ndarray) -> float:
        """Calcula probabilidade de fala para um frame de audio.

        Se o frame for maior que 512 samples, e dividido em sub-frames
        de 512 samples e processado sequencialmente (preservando estado
        interno do Silero). Retorna a probabilidade maxima entre sub-frames.

        Args:
            frame: Array numpy float32 mono, 16kHz.

        Returns:
            Probabilidade de fala entre 0.0 e 1.0.
        """
        self._ensure_model_loaded()

        chunk_size = 512
        if len(frame) <= chunk_size:
            tensor = self._to_tensor(frame) if self._to_tensor is not None else frame
            prob = self._model(tensor, self._sample_rate)  # type: ignore[misc, operator]
            return float(prob.item())

        max_prob = 0.0
        for offset in range(0, len(frame), chunk_size):
            sub_frame = frame[offset : offset + chunk_size]
            if len(sub_frame) < chunk_size:
                break
            tensor = self._to_tensor(sub_frame) if self._to_tensor is not None else sub_frame
            prob = self._model(tensor, self._sample_rate)  # type: ignore[misc, operator]
            max_prob = max(max_prob, float(prob.item()))
        return max_prob

    def is_speech(self, frame: np.ndarray) -> bool:
        """Verifica se frame contem fala (prob > threshold).

        Args:
            frame: Array numpy float32 mono, 16kHz.

        Returns:
            True se probabilidade de fala > threshold.
        """
        return self.get_speech_probability(frame) > self._threshold

    def reset(self) -> None:
        """Reseta estado interno do modelo (para inicio de nova sessao).

        Silero VAD mantem estado entre chamadas (contexto temporal).
        Chamar reset() no inicio de cada sessao garante que o estado
        anterior nao interfere.
        """
        if self._model is not None and hasattr(self._model, "reset_states"):
            self._model.reset_states()
