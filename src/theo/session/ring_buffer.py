"""Ring Buffer — buffer circular pre-alocado para armazenamento de audio.

Buffer circular de tamanho fixo que armazena frames de audio recentes da sessao.
Pre-aloca um bytearray no __init__ e faz zero allocations durante streaming.

Essencial para:
- Recovery apos crash de worker (reprocessar audio nao commitado)
- LocalAgreement (acumular windows de 3-5s para comparacao entre passes)

O offset absoluto (total_written) e monotonicamente crescente e nunca reseta.
Permite rastreamento preciso de posicoes no WAL.

Read fence (last_committed_offset) protege dados nao commitados de sobrescrita.
Dados antes do fence podem ser sobrescritos pelo wrap-around; dados entre o
fence e total_written sao protegidos. Se uncommitted_bytes / capacity > 90%
apos um write, o callback on_force_commit e invocado para notificar a sessao.

Sem threading/locking — single-threaded no event loop asyncio.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from Macaw.exceptions import BufferOverrunError

if TYPE_CHECKING:
    from collections.abc import Callable

# Threshold de uso nao-commitado que dispara force commit (90%)
_FORCE_COMMIT_THRESHOLD = 0.90


class RingBuffer:
    """Buffer circular pre-alocado para armazenamento de audio PCM.

    Parametros:
        duration_s: Duracao do buffer em segundos (default: 60s).
        sample_rate: Taxa de amostragem em Hz (default: 16000).
        bytes_per_sample: Bytes por amostra (default: 2 para PCM 16-bit).
        on_force_commit: Callback opcional invocado quando uncommitted_bytes
            ultrapassa 90% da capacidade. Recebe total_written como argumento.
            Callback sincrono (nao async) — chamado de dentro de write().

    O buffer e pre-alocado no __init__ e nenhuma allocation ocorre durante
    operacoes de write/read. O tamanho default (60s * 16000 * 2) = 1,920,000 bytes.
    """

    __slots__ = (
        "_buffer",
        "_capacity_bytes",
        "_on_force_commit",
        "_read_fence",
        "_total_written",
        "_write_pos",
    )

    def __init__(
        self,
        duration_s: float = 60.0,
        sample_rate: int = 16000,
        bytes_per_sample: int = 2,
        on_force_commit: Callable[[int], None] | None = None,
    ) -> None:
        self._capacity_bytes: int = int(duration_s * sample_rate * bytes_per_sample)
        if self._capacity_bytes <= 0:
            msg = f"Capacidade do buffer deve ser positiva, got {self._capacity_bytes}"
            raise ValueError(msg)
        self._buffer: bytearray = bytearray(self._capacity_bytes)
        self._write_pos: int = 0
        self._total_written: int = 0
        self._read_fence: int = 0
        self._on_force_commit = on_force_commit

    @property
    def capacity_bytes(self) -> int:
        """Tamanho total do buffer em bytes."""
        return self._capacity_bytes

    @property
    def total_written(self) -> int:
        """Offset absoluto total escrito (monotonicamente crescente, nunca reseta)."""
        return self._total_written

    @property
    def used_bytes(self) -> int:
        """Bytes atualmente usados no buffer (min de total_written e capacity)."""
        return min(self._total_written, self._capacity_bytes)

    @property
    def usage_percent(self) -> float:
        """Porcentagem de uso do buffer (0.0 a 100.0)."""
        return self.used_bytes / self._capacity_bytes * 100.0

    @property
    def read_fence(self) -> int:
        """Offset absoluto do last_committed_offset (read fence).

        Dados antes deste offset podem ser sobrescritos pelo wrap-around.
        Dados entre read_fence e total_written sao protegidos.
        """
        return self._read_fence

    @property
    def uncommitted_bytes(self) -> int:
        """Bytes entre read_fence e total_written (dados nao commitados)."""
        return self._total_written - self._read_fence

    @property
    def available_for_write_bytes(self) -> int:
        """Bytes que podem ser escritos sem sobrescrever dados nao commitados.

        Calculo: capacidade total menos bytes nao commitados que ocupam espaco
        no buffer circular. Se o buffer ainda nao deu volta, todo o espaco
        restante esta disponivel.
        """
        uncommitted = self.uncommitted_bytes
        if uncommitted >= self._capacity_bytes:
            return 0
        return self._capacity_bytes - uncommitted

    def commit(self, offset: int) -> None:
        """Avanca o read fence para o offset dado.

        Marca dados antes do offset como "seguros para sobrescrever".
        O offset deve estar entre o fence atual e total_written (inclusive).

        Args:
            offset: Novo offset do read fence (last_committed_offset).

        Raises:
            ValueError: Se offset < read_fence atual ou offset > total_written.
        """
        if offset < self._read_fence:
            msg = (
                f"Commit offset ({offset}) nao pode ser menor que "
                f"read_fence atual ({self._read_fence})"
            )
            raise ValueError(msg)

        if offset > self._total_written:
            msg = (
                f"Commit offset ({offset}) nao pode ser maior que "
                f"total_written ({self._total_written})"
            )
            raise ValueError(msg)

        self._read_fence = offset

    def write(self, data: bytes) -> int:
        """Escreve dados no buffer na posicao circular atual.

        Protege dados nao commitados: se a escrita sobrescreveria bytes entre
        read_fence e total_written, levanta BufferOverrunError.

        Apos escrita bem-sucedida, verifica se uncommitted_bytes > 90% da
        capacidade e invoca on_force_commit se configurado.

        Args:
            data: Bytes a serem escritos no buffer.

        Returns:
            Offset absoluto do inicio da escrita (total_written antes da operacao).

        Raises:
            BufferOverrunError: Se a escrita sobrescreveria dados nao commitados.
        """
        data_len = len(data)
        if data_len == 0:
            return self._total_written

        # Verificar se a escrita sobrescreveria dados nao commitados.
        # So verificamos quando ha dados nao commitados (read_fence < total_written).
        # Quando read_fence == total_written (tudo commitado), a escrita e livre
        # porque nao ha nada para proteger — mesmo que data_len > capacity.
        uncommitted = self.uncommitted_bytes
        if uncommitted > 0:
            available = self._capacity_bytes - uncommitted
            if available < 0:
                available = 0
            if data_len > available:
                msg = (
                    f"Escrita de {data_len} bytes sobrescreveria dados nao commitados. "
                    f"Disponivel: {available} bytes, "
                    f"read_fence={self._read_fence}, total_written={self._total_written}"
                )
                raise BufferOverrunError(msg)

        start_offset = self._total_written
        mv = memoryview(self._buffer)

        if data_len >= self._capacity_bytes:
            # Dados maiores que buffer: retemos apenas os ultimos capacity_bytes.
            # Este ramo so e alcancado quando available_for_write >= capacity,
            # ou seja, quando read_fence == total_written (tudo commitado).
            trimmed = data[-self._capacity_bytes :]
            new_total = self._total_written + data_len
            retained_start_offset = new_total - self._capacity_bytes
            retained_start_pos = retained_start_offset % self._capacity_bytes
            if retained_start_pos == 0:
                mv[:] = trimmed
            else:
                first_part = self._capacity_bytes - retained_start_pos
                mv[retained_start_pos:] = trimmed[:first_part]
                mv[:retained_start_pos] = trimmed[first_part:]
            self._write_pos = new_total % self._capacity_bytes
            self._total_written = new_total
            self._check_force_commit()
            return start_offset

        # Espaco ate o fim do buffer circular
        space_to_end = self._capacity_bytes - self._write_pos

        if data_len <= space_to_end:
            # Cabe sem wrap-around
            mv[self._write_pos : self._write_pos + data_len] = data
        else:
            # Wrap-around: escreve em duas partes
            first_part = space_to_end
            mv[self._write_pos : self._write_pos + first_part] = data[:first_part]
            second_part = data_len - first_part
            mv[:second_part] = data[first_part:]

        self._write_pos = (self._write_pos + data_len) % self._capacity_bytes
        self._total_written += data_len

        self._check_force_commit()
        return start_offset

    def _check_force_commit(self) -> None:
        """Verifica se uncommitted_bytes ultrapassou 90% e notifica."""
        if self._on_force_commit is None:
            return

        uncommitted = self.uncommitted_bytes
        if uncommitted <= 0:
            return

        if uncommitted / self._capacity_bytes > _FORCE_COMMIT_THRESHOLD:
            self._on_force_commit(self._total_written)

    def read(self, offset: int, length: int) -> bytes:
        """Le dados do buffer a partir de um offset absoluto.

        Converte o offset absoluto para posicao circular e le os dados.
        Se os dados cruzam a borda do buffer (wrap-around), le em duas partes.

        Args:
            offset: Offset absoluto de inicio da leitura.
            length: Quantidade de bytes a ler.

        Returns:
            Copia dos dados lidos como bytes.

        Raises:
            BufferOverrunError: Se o offset e muito antigo (dados ja sobrescritos)
                ou se offset + length excede total_written.
            ValueError: Se length e negativo ou offset e negativo.
        """
        if length == 0:
            return b""

        if offset < 0:
            msg = f"Offset nao pode ser negativo: {offset}"
            raise ValueError(msg)

        if length < 0:
            msg = f"Length nao pode ser negativo: {length}"
            raise ValueError(msg)

        end_offset = offset + length

        # Verificar se os dados ainda estao disponiveis no buffer
        if end_offset > self._total_written:
            msg = (
                f"Leitura alem do escrito: offset={offset}, length={length}, "
                f"total_written={self._total_written}"
            )
            raise BufferOverrunError(msg)

        # Dados mais antigos disponiveis: total_written - capacity (ou 0 se buffer nao deu volta)
        oldest_available = max(0, self._total_written - self._capacity_bytes)
        if offset < oldest_available:
            msg = f"Dados ja sobrescritos: offset={offset}, oldest_available={oldest_available}"
            raise BufferOverrunError(msg)

        # Converter offset absoluto para posicao circular
        circular_pos = offset % self._capacity_bytes
        mv = memoryview(self._buffer)

        space_to_end = self._capacity_bytes - circular_pos

        if length <= space_to_end:
            # Leitura sem wrap-around
            return bytes(mv[circular_pos : circular_pos + length])

        # Wrap-around: ler em duas partes
        first_part = bytes(mv[circular_pos : circular_pos + space_to_end])
        second_part = bytes(mv[: length - space_to_end])
        return first_part + second_part

    def read_from_offset(self, offset: int) -> bytes:
        """Le todos os dados do offset ate o total_written atual.

        Util para recovery: ler tudo apos o ultimo commit.

        Args:
            offset: Offset absoluto de inicio da leitura.

        Returns:
            Copia dos dados lidos como bytes.

        Raises:
            BufferOverrunError: Se o offset e muito antigo (dados ja sobrescritos).
            ValueError: Se offset e negativo.
        """
        if offset < 0:
            msg = f"Offset nao pode ser negativo: {offset}"
            raise ValueError(msg)

        if offset >= self._total_written:
            return b""

        length = self._total_written - offset
        return self.read(offset, length)
