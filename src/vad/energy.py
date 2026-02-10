"""Energy Pre-filter para Voice Activity Detection.

Pre-filtro baseado em energia (RMS) e spectral flatness para reduzir
chamadas ao Silero VAD. Frames com baixa energia e espectro plano
(indicando ruido branco ou silencio) sao classificados como silencio
sem invocar o modelo neural.

Reducao estimada de falsos positivos: 60-70% em ambientes ruidosos.
Custo: ~0.1ms/frame.
"""

from __future__ import annotations

import numpy as np

from Macaw._types import VADSensitivity

# Thresholds de energia (dBFS) por nivel de sensibilidade.
# Valores mais negativos = mais sensivel (detecta sons mais fracos).
_ENERGY_THRESHOLDS: dict[VADSensitivity, float] = {
    VADSensitivity.HIGH: -50.0,  # Muito sensivel (sussurro, banking)
    VADSensitivity.NORMAL: -40.0,  # Conversacao normal (default)
    VADSensitivity.LOW: -30.0,  # Ambiente ruidoso, call center
}

# Threshold de spectral flatness acima do qual o espectro e considerado
# plano (ruido branco / silencio). Fala tonal tem flatness baixa (~0.1-0.5).
_SPECTRAL_FLATNESS_THRESHOLD = 0.8

# Minimo de samples para que FFT produza resultado significativo.
_MIN_SAMPLES_FOR_FFT = 2

# Epsilon para evitar log(0) e divisao por zero.
_EPSILON = 1e-10


class EnergyPreFilter:
    """Pre-filtro baseado em energia para reduzir chamadas ao Silero VAD.

    Calcula RMS e spectral flatness do frame. Se RMS em dBFS < threshold
    E spectral flatness > 0.8 (indica ruido branco/silencio), classifica
    como silencio sem precisar chamar o Silero VAD.

    Custo: ~0.1ms/frame.
    """

    def __init__(self, sensitivity: VADSensitivity = VADSensitivity.NORMAL) -> None:
        self._sensitivity = sensitivity
        self._energy_threshold_dbfs = _ENERGY_THRESHOLDS[sensitivity]

    @property
    def energy_threshold_dbfs(self) -> float:
        """Threshold atual em dBFS."""
        return self._energy_threshold_dbfs

    def is_silence(self, frame: np.ndarray) -> bool:
        """Verifica se o frame e silencio baseado em energia e spectral flatness.

        Args:
            frame: Array numpy float32 mono, qualquer tamanho
                   (tipicamente 64ms = 1024 samples a 16kHz).

        Returns:
            True se o frame e classificado como silencio
            (RMS baixo E spectral flatness alta).
        """
        if len(frame) < _MIN_SAMPLES_FOR_FFT:
            return True

        rms = np.sqrt(np.mean(frame**2))
        rms_dbfs = 20.0 * np.log10(rms + _EPSILON)

        if rms_dbfs >= self._energy_threshold_dbfs:
            return False

        magnitude = np.abs(np.fft.rfft(frame))
        magnitude = np.maximum(magnitude, _EPSILON)

        log_magnitude = np.log(magnitude)
        geometric_mean = np.exp(np.mean(log_magnitude))
        arithmetic_mean = np.mean(magnitude)

        spectral_flatness = geometric_mean / arithmetic_mean

        return bool(spectral_flatness > _SPECTRAL_FLATNESS_THRESHOLD)
