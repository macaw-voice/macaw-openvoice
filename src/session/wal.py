"""WAL In-Memory -- Write-Ahead Log para recovery de sessao.

Registra checkpoints apos cada transcript.final emitido. Permite recovery
sem duplicacao apos crash de worker.

Deliberadamente simples: in-memory, um registro, sobrescreve.
Nao e log append-only -- e um ponteiro para "onde estamos".
O WAL e consultado durante recovery (M6-07) para determinar o ultimo
segmento confirmado, o offset no ring buffer e o timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WALCheckpoint:
    """Checkpoint registrado no WAL.

    Representa o estado confirmado da sessao no momento em que
    um transcript.final foi emitido ao cliente.

    Atributos:
        segment_id: ID do segmento confirmado.
        buffer_offset: Offset absoluto no Ring Buffer ate onde audio
            foi processado (total_written no momento do commit).
        timestamp_ms: Timestamp monotonic em ms do momento do checkpoint.
    """

    segment_id: int
    buffer_offset: int
    timestamp_ms: int


class SessionWAL:
    """Write-Ahead Log in-memory para sessoes de streaming.

    Registra checkpoints apos cada transcript.final emitido.
    Permite recovery sem duplicacao apos crash de worker.

    Deliberadamente simples: in-memory, um registro, sobrescreve.
    Nao e log append-only -- e um ponteiro para "onde estamos".

    Thread-safety: nao necessaria -- single-threaded no event loop asyncio,
    mesma garantia do RingBuffer.
    """

    __slots__ = ("_checkpoint",)

    def __init__(self) -> None:
        self._checkpoint = WALCheckpoint(segment_id=0, buffer_offset=0, timestamp_ms=0)

    @property
    def last_committed_segment_id(self) -> int:
        """ID do ultimo segmento confirmado."""
        return self._checkpoint.segment_id

    @property
    def last_committed_buffer_offset(self) -> int:
        """Offset no Ring Buffer do ultimo commit."""
        return self._checkpoint.buffer_offset

    @property
    def last_committed_timestamp_ms(self) -> int:
        """Timestamp monotonic em ms do ultimo commit."""
        return self._checkpoint.timestamp_ms

    @property
    def checkpoint(self) -> WALCheckpoint:
        """Checkpoint atual (ultimo registrado)."""
        return self._checkpoint

    def record_checkpoint(
        self,
        segment_id: int,
        buffer_offset: int,
        timestamp_ms: int,
    ) -> None:
        """Registra checkpoint atomico apos transcript.final.

        Cada checkpoint sobrescreve o anterior (WAL in-memory, nao append-only).
        A atomicidade e garantida pela atribuicao de referencia em Python
        (single assignment no event loop, sem threading).

        Args:
            segment_id: ID do segmento confirmado.
            buffer_offset: Offset no Ring Buffer ate onde audio foi processado.
            timestamp_ms: Timestamp monotonic em ms do momento do checkpoint.
        """
        self._checkpoint = WALCheckpoint(
            segment_id=segment_id,
            buffer_offset=buffer_offset,
            timestamp_ms=timestamp_ms,
        )
