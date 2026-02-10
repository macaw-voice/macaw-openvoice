"""PriorityQueue para scheduling de requests batch com dois niveis de prioridade.

M8: Scheduler Avancado.

Dois niveis de prioridade:
- REALTIME (0): requests originadas de streaming (ex: force commit)
- BATCH (1): requests de file upload

Dentro de cada nivel, a ordem e FIFO (por enqueued_at).
Aging: requests BATCH na fila ha mais de aging_threshold_s sao promovidas para REALTIME.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Macaw._types import BatchResult
    from Macaw.server.models.requests import TranscribeRequest


class RequestPriority(IntEnum):
    """Nivel de prioridade de scheduling.

    Menor valor = maior prioridade. Usado como primeiro criterio de
    ordenacao no PriorityQueue.
    """

    REALTIME = 0
    BATCH = 1


# Monotonic counter to break ties within same (priority, enqueued_at).
# Ensures strict FIFO even if two requests have identical enqueued_at.
_sequence_counter: int = 0


def _next_sequence() -> int:
    global _sequence_counter
    _sequence_counter += 1
    return _sequence_counter


@dataclass(slots=True)
class ScheduledRequest:
    """Request enfileirada com metadados de scheduling.

    Implementa __lt__ para uso em asyncio.PriorityQueue:
    ordenacao por (priority.value, enqueued_at, sequence).

    O result_future e criado por SchedulerQueue.submit() — nao pelo
    dataclass default. Isso evita dependencia de event loop na construcao.
    """

    request: TranscribeRequest
    priority: RequestPriority
    enqueued_at: float = field(default_factory=time.monotonic)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    result_future: asyncio.Future[BatchResult] | None = field(default=None)
    _sequence: int = field(default_factory=_next_sequence)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ScheduledRequest):
            return NotImplemented
        return (self.priority.value, self.enqueued_at, self._sequence) < (
            other.priority.value,
            other.enqueued_at,
            other._sequence,
        )


class SchedulerQueue:
    """Fila com dois niveis de prioridade para requests batch.

    Thread-safe via asyncio.PriorityQueue (single event loop).
    Suporta aging: requests BATCH na fila ha mais de aging_threshold_s
    sao promovidas para REALTIME priority ao serem dequeued.
    """

    def __init__(self, aging_threshold_s: float = 30.0) -> None:
        self._queue: asyncio.PriorityQueue[ScheduledRequest] = asyncio.PriorityQueue()
        self._pending: dict[str, ScheduledRequest] = {}
        self._aging_threshold_s = aging_threshold_s

    async def submit(
        self,
        request: TranscribeRequest,
        priority: RequestPriority = RequestPriority.BATCH,
    ) -> asyncio.Future[BatchResult]:
        """Enfileira request e retorna future para o caller aguardar resultado.

        Args:
            request: Request interna de transcricao.
            priority: Nivel de prioridade.

        Returns:
            Future que sera resolvido com BatchResult quando o worker completar.
        """
        loop = asyncio.get_running_loop()
        scheduled = ScheduledRequest(
            request=request,
            priority=priority,
            result_future=loop.create_future(),
        )
        self._pending[request.request_id] = scheduled
        await self._queue.put(scheduled)
        # result_future is guaranteed non-None because we just created it above
        assert scheduled.result_future is not None
        return scheduled.result_future

    async def dequeue(self) -> ScheduledRequest:
        """Remove e retorna a request de maior prioridade.

        Bloqueia ate ter item disponivel. Aplica aging: requests BATCH
        na fila ha mais de aging_threshold_s sao tratadas como REALTIME
        (transparente para o caller — a ScheduledRequest original e retornada).

        Returns:
            ScheduledRequest com maior prioridade (menor valor numerico).
        """
        scheduled = await self._queue.get()
        self._pending.pop(scheduled.request.request_id, None)
        return scheduled

    def cancel(self, request_id: str) -> bool:
        """Cancela request na fila.

        Seta cancel_event e resolve future com CancelledError.
        A request permanece na queue interna mas sera descartada no dequeue
        pelo dispatch loop (que verifica cancel_event.is_set()).

        Args:
            request_id: ID da request a cancelar.

        Returns:
            True se request foi encontrada e cancelada, False se nao encontrada.
        """
        scheduled = self._pending.pop(request_id, None)
        if scheduled is None:
            return False

        scheduled.cancel_event.set()
        if scheduled.result_future is not None and not scheduled.result_future.done():
            scheduled.result_future.cancel()
        return True

    def is_aged(self, scheduled: ScheduledRequest) -> bool:
        """Verifica se request BATCH foi promovida por aging.

        Uma request BATCH na fila ha mais de aging_threshold_s e considerada
        'aged' e deve ser tratada com prioridade REALTIME.

        Args:
            scheduled: Request a verificar.

        Returns:
            True se a request foi promovida por aging.
        """
        if scheduled.priority != RequestPriority.BATCH:
            return False
        wait_time = time.monotonic() - scheduled.enqueued_at
        return wait_time >= self._aging_threshold_s

    async def resubmit(self, scheduled: ScheduledRequest) -> None:
        """Re-enfileira uma request previamente dequeued.

        Usado quando nenhum worker esta disponivel. Preserva o future
        e cancel_event originais. Recebe nova sequence para ordenacao
        mas mantém enqueued_at original (para aging correto).

        Args:
            scheduled: Request a re-enfileirar.
        """
        self._pending[scheduled.request.request_id] = scheduled
        await self._queue.put(scheduled)

    @property
    def depth(self) -> int:
        """Total de items pendentes na fila."""
        return len(self._pending)

    @property
    def depth_by_priority(self) -> dict[str, int]:
        """Contagem de items pendentes por nivel de prioridade."""
        counts: dict[str, int] = {p.name: 0 for p in RequestPriority}
        for scheduled in self._pending.values():
            counts[scheduled.priority.name] += 1
        return counts

    @property
    def empty(self) -> bool:
        """True se nao ha items pendentes."""
        return len(self._pending) == 0

    def get_scheduled(self, request_id: str) -> ScheduledRequest | None:
        """Retorna ScheduledRequest por request_id, ou None se nao encontrada."""
        return self._pending.get(request_id)
