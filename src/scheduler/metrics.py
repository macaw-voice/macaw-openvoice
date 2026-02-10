"""Metricas Prometheus para o Scheduler batch.

Metricas sao opcionais: se prometheus_client nao estiver instalado,
o modulo exporta None para cada metrica e o codigo consumidor deve
verificar antes de usar (pattern identico a Macaw.session.metrics).

Metricas definidas (M8):
- Macaw_scheduler_queue_depth: Gauge de profundidade da fila por prioridade
- Macaw_scheduler_queue_wait_seconds: Histogram de tempo na fila
- Macaw_scheduler_grpc_duration_seconds: Histogram de tempo de gRPC call
- Macaw_scheduler_cancel_latency_seconds: Histogram de latencia de cancel
- Macaw_scheduler_batch_size: Histogram de tamanho dos batches despachados
- Macaw_scheduler_requests_total: Counter de requests por prioridade e status
- Macaw_scheduler_aging_promotions_total: Counter de promotions por aging
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prometheus_client import Counter, Gauge, Histogram

try:
    from prometheus_client import Counter as _Counter
    from prometheus_client import Gauge as _Gauge
    from prometheus_client import Histogram as _Histogram

    scheduler_queue_depth: Gauge | None = _Gauge(
        "Macaw_scheduler_queue_depth",
        "Number of requests pending in the scheduler queue",
        ["priority"],
    )

    scheduler_queue_wait_seconds: Histogram | None = _Histogram(
        "Macaw_scheduler_queue_wait_seconds",
        "Time spent waiting in the scheduler queue",
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
    )

    scheduler_grpc_duration_seconds: Histogram | None = _Histogram(
        "Macaw_scheduler_grpc_duration_seconds",
        "Duration of gRPC TranscribeFile calls to workers",
        buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    )

    scheduler_cancel_latency_seconds: Histogram | None = _Histogram(
        "Macaw_scheduler_cancel_latency_seconds",
        "Latency of cancel propagation to workers via gRPC",
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25),
    )

    scheduler_batch_size: Histogram | None = _Histogram(
        "Macaw_scheduler_batch_size",
        "Number of requests per batch dispatch",
        buckets=(1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16),
    )

    scheduler_requests_total: Counter | None = _Counter(
        "Macaw_scheduler_requests_total",
        "Total scheduler requests by priority and outcome",
        ["priority", "status"],
    )

    scheduler_aging_promotions_total: Counter | None = _Counter(
        "Macaw_scheduler_aging_promotions_total",
        "Requests promoted from BATCH to REALTIME priority by aging",
    )

    HAS_METRICS = True

except ImportError:
    scheduler_queue_depth = None
    scheduler_queue_wait_seconds = None
    scheduler_grpc_duration_seconds = None
    scheduler_cancel_latency_seconds = None
    scheduler_batch_size = None
    scheduler_requests_total = None
    scheduler_aging_promotions_total = None

    HAS_METRICS = False
