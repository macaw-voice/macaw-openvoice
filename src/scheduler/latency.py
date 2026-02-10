"""LatencyTracker — orcamento de latencia per-request.

M8-07: Registra timestamps por fase do pipeline de cada request batch
e calcula metricas de latencia (queue_wait, grpc_time, total_time).

Usado pelo Scheduler para instrumentacao. Entries sao automaticamente
removidas apos complete() ou apos TTL de 60s para prevenir memory leak.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from Macaw.logging import get_logger

logger = get_logger("scheduler.latency")

# TTL para entries nao completadas (previne leak em crash sem cancel)
_DEFAULT_TTL_S = 60.0


@dataclass(slots=True)
class _RequestTimestamps:
    """Timestamps de cada fase do pipeline para uma request."""

    enqueue_time: float = 0.0
    dequeue_time: float = 0.0
    grpc_start_time: float = 0.0
    complete_time: float = 0.0


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Resumo de latencia de uma request completada.

    Todos os valores em segundos.
    """

    request_id: str
    queue_wait: float
    grpc_time: float
    total_time: float
    enqueue_time: float
    dequeue_time: float
    grpc_start_time: float
    complete_time: float


class LatencyTracker:
    """Rastreia latencia per-request por fase do pipeline.

    Fases registradas:
    1. ``start()``      — request enfileirada (enqueue_time)
    2. ``dequeued()``   — request retirada da fila (dequeue_time)
    3. ``grpc_started()``— chamada gRPC iniciada (grpc_start_time)
    4. ``complete()``   — resposta recebida do worker (complete_time)

    Apos ``complete()``, calcula metricas derivadas:
    - queue_wait = dequeue_time - enqueue_time
    - grpc_time  = complete_time - grpc_start_time
    - total_time = complete_time - enqueue_time

    Entries sao removidas automaticamente apos ``complete()`` e
    ``get_summary()`` ou apos TTL via ``cleanup()``.

    Args:
        ttl_s: Tempo em segundos antes de remover entries nao completadas.
    """

    def __init__(self, *, ttl_s: float = _DEFAULT_TTL_S) -> None:
        if ttl_s <= 0:
            msg = f"ttl_s must be positive, got {ttl_s}"
            raise ValueError(msg)
        self._ttl_s = ttl_s
        self._entries: dict[str, _RequestTimestamps] = {}
        self._summaries: dict[str, LatencySummary] = {}

    @property
    def active_count(self) -> int:
        """Numero de requests sendo rastreadas (nao completadas)."""
        return len(self._entries)

    def start(self, request_id: str) -> None:
        """Registra enqueue_time para uma request.

        Chamado quando a request e submetida ao scheduler.
        """
        ts = _RequestTimestamps(enqueue_time=time.monotonic())
        self._entries[request_id] = ts

    def dequeued(self, request_id: str) -> None:
        """Registra dequeue_time para uma request.

        Chamado quando a request e retirada da fila de prioridade.
        """
        entry = self._entries.get(request_id)
        if entry is None:
            logger.debug("latency_dequeued_unknown", request_id=request_id)
            return
        entry.dequeue_time = time.monotonic()

    def grpc_started(self, request_id: str) -> None:
        """Registra grpc_start_time para uma request.

        Chamado imediatamente antes do gRPC TranscribeFile.
        """
        entry = self._entries.get(request_id)
        if entry is None:
            logger.debug("latency_grpc_started_unknown", request_id=request_id)
            return
        entry.grpc_start_time = time.monotonic()

    def complete(self, request_id: str) -> LatencySummary | None:
        """Registra complete_time e calcula summary.

        Chamado quando a resposta gRPC e recebida (sucesso ou erro).
        Remove a entry ativa e armazena o summary para consulta.

        Returns:
            LatencySummary se a request era rastreada, None caso contrario.
        """
        entry = self._entries.pop(request_id, None)
        if entry is None:
            logger.debug("latency_complete_unknown", request_id=request_id)
            return None

        entry.complete_time = time.monotonic()

        summary = LatencySummary(
            request_id=request_id,
            queue_wait=entry.dequeue_time - entry.enqueue_time if entry.dequeue_time > 0 else 0.0,
            grpc_time=entry.complete_time - entry.grpc_start_time
            if entry.grpc_start_time > 0
            else 0.0,
            total_time=entry.complete_time - entry.enqueue_time,
            enqueue_time=entry.enqueue_time,
            dequeue_time=entry.dequeue_time,
            grpc_start_time=entry.grpc_start_time,
            complete_time=entry.complete_time,
        )

        self._summaries[request_id] = summary

        logger.debug(
            "latency_complete",
            request_id=request_id,
            queue_wait_ms=round(summary.queue_wait * 1000, 1),
            grpc_time_ms=round(summary.grpc_time * 1000, 1),
            total_time_ms=round(summary.total_time * 1000, 1),
        )

        return summary

    def get_summary(self, request_id: str) -> LatencySummary | None:
        """Retorna summary de uma request completada.

        Remove o summary apos retornar (one-shot read).

        Returns:
            LatencySummary se disponivel, None caso contrario.
        """
        return self._summaries.pop(request_id, None)

    def discard(self, request_id: str) -> None:
        """Remove uma request do tracker sem completar.

        Usado para requests canceladas que nao chegam a complete().
        """
        self._entries.pop(request_id, None)
        self._summaries.pop(request_id, None)

    def cleanup(self) -> int:
        """Remove entries mais velhas que TTL.

        Previne memory leak em caso de requests que nunca completam
        (ex: crash de worker sem propagacao de cancel).

        Returns:
            Numero de entries removidas.
        """
        now = time.monotonic()
        cutoff = now - self._ttl_s

        expired = [rid for rid, ts in self._entries.items() if ts.enqueue_time < cutoff]

        for rid in expired:
            self._entries.pop(rid, None)
            logger.debug("latency_ttl_expired", request_id=rid)

        # Cleanup summaries nao consumidos tambem
        expired_summaries = [
            rid for rid, summary in self._summaries.items() if summary.enqueue_time < cutoff
        ]
        for rid in expired_summaries:
            self._summaries.pop(rid, None)

        total_removed = len(expired) + len(expired_summaries)
        if total_removed > 0:
            logger.debug(
                "latency_cleanup",
                entries_removed=len(expired),
                summaries_removed=len(expired_summaries),
            )
        return total_removed
