"""Configuracao do Audio Preprocessing Pipeline."""

from __future__ import annotations

from pydantic import BaseModel


class PreprocessingConfig(BaseModel):
    """Configuracao do pipeline de preprocessamento de audio.

    Cada stage e toggleavel independentemente.
    """

    resample: bool = True
    target_sample_rate: int = 16000
    dc_remove: bool = True
    dc_remove_cutoff_hz: int = 20
    gain_normalize: bool = True
    target_dbfs: float = -3.0
    normalize_window_ms: int = 500
    denoise: bool = False
    denoise_engine: str = "rnnoise"
