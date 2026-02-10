"""Metricas Prometheus para TTS.

Metricas sao opcionais: se prometheus_client nao estiver instalado,
o modulo exporta None para cada metrica e o codigo consumidor deve
verificar antes de usar.

Metricas definidas (M9):
- Macaw_tts_ttfb_seconds: Time to First Byte (primeiro chunk de audio apos tts.speak)
- Macaw_tts_synthesis_duration_seconds: Duracao total da sintese (primeiro ao ultimo chunk)
- Macaw_tts_requests_total: Counter de requests TTS por status (ok/error/cancelled)
- Macaw_tts_active_sessions: Gauge de sessoes com TTS ativo
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prometheus_client import Counter, Gauge, Histogram

try:
    from prometheus_client import Counter as _Counter
    from prometheus_client import Gauge as _Gauge
    from prometheus_client import Histogram as _Histogram

    tts_ttfb_seconds: Histogram | None = _Histogram(
        "Macaw_tts_ttfb_seconds",
        "Time to first audio byte after tts.speak command",
        buckets=(0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0),
    )

    tts_synthesis_duration_seconds: Histogram | None = _Histogram(
        "Macaw_tts_synthesis_duration_seconds",
        "Total duration of TTS synthesis (first to last chunk)",
        buckets=(0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
    )

    tts_requests_total: Counter | None = _Counter(
        "Macaw_tts_requests_total",
        "Total TTS requests by status",
        ["status"],
    )

    tts_active_sessions: Gauge | None = _Gauge(
        "Macaw_tts_active_sessions",
        "Number of sessions with active TTS synthesis",
    )

    HAS_TTS_METRICS = True

except ImportError:
    tts_ttfb_seconds = None
    tts_synthesis_duration_seconds = None
    tts_requests_total = None
    tts_active_sessions = None

    HAS_TTS_METRICS = False
