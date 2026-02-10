"""Metricas Prometheus para streaming STT.

Metricas sao opcionais: se prometheus_client nao estiver instalado,
o modulo exporta None para cada metrica e o codigo consumidor deve
verificar antes de usar.

Metricas definidas (M5):
- Macaw_stt_ttfb_seconds: Time to First Byte (primeiro partial/final apos speech start)
- Macaw_stt_final_delay_seconds: Delay do final transcript apos fim de fala
- Macaw_stt_active_sessions: Gauge de sessoes WebSocket ativas
- Macaw_stt_vad_events_total: Counter de eventos VAD por tipo (speech_start, speech_end)

Metricas adicionadas (M6):
- Macaw_stt_session_duration_seconds: Duracao total de sessoes encerradas
- Macaw_stt_segments_force_committed_total: Segmentos com force commit (ring buffer >90%)
- Macaw_stt_confidence_avg: Histograma de confidence dos transcript.final
- Macaw_stt_worker_recoveries_total: Counter de recovery attempts por resultado

Metricas adicionadas (M9):
- Macaw_stt_muted_frames_total: Frames descartados por mute-on-speak (TTS ativo)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prometheus_client import Counter, Gauge, Histogram

try:
    from prometheus_client import Counter as _Counter
    from prometheus_client import Gauge as _Gauge
    from prometheus_client import Histogram as _Histogram

    stt_ttfb_seconds: Histogram | None = _Histogram(
        "Macaw_stt_ttfb_seconds",
        "Time to first byte (first partial transcript after speech start)",
        buckets=(0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0, 5.0),
    )

    stt_final_delay_seconds: Histogram | None = _Histogram(
        "Macaw_stt_final_delay_seconds",
        "Delay of final transcript after end of speech",
        buckets=(0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0, 5.0),
    )

    stt_active_sessions: Gauge | None = _Gauge(
        "Macaw_stt_active_sessions",
        "Number of active WebSocket streaming sessions",
    )

    stt_vad_events_total: Counter | None = _Counter(
        "Macaw_stt_vad_events_total",
        "Total VAD events by type",
        ["event_type"],
    )

    # M6 metrics

    stt_session_duration_seconds: Histogram | None = _Histogram(
        "Macaw_stt_session_duration_seconds",
        "Total duration of completed streaming sessions",
        buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),
    )

    stt_segments_force_committed_total: Counter | None = _Counter(
        "Macaw_stt_segments_force_committed_total",
        "Segments force committed due to ring buffer exceeding 90% capacity",
    )

    stt_confidence_avg: Histogram | None = _Histogram(
        "Macaw_stt_confidence_avg",
        "Confidence scores of final transcripts (proxy for WER)",
        buckets=(0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.99),
    )

    stt_worker_recoveries_total: Counter | None = _Counter(
        "Macaw_stt_worker_recoveries_total",
        "Worker crash recovery attempts by result",
        ["result"],
    )

    # M9 metrics

    stt_muted_frames_total: Counter | None = _Counter(
        "Macaw_stt_muted_frames_total",
        "Frames discarded by mute-on-speak (TTS active)",
    )

    HAS_METRICS = True

except ImportError:
    stt_ttfb_seconds = None
    stt_final_delay_seconds = None
    stt_active_sessions = None
    stt_vad_events_total = None
    stt_session_duration_seconds = None
    stt_segments_force_committed_total = None
    stt_confidence_avg = None
    stt_worker_recoveries_total = None
    stt_muted_frames_total = None

    HAS_METRICS = False
