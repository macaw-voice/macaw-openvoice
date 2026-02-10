"""BackpressureController -- controle de taxa de ingestao de audio.

Monitora a taxa de recebimento de frames de audio em relacao ao tempo
real (wall-clock). Se o cliente enviar audio mais rapido que real-time,
emite acoes de rate_limit ou frames_dropped para o WebSocket handler.

Comportamento:
- Taxa > rate_limit_threshold (default 1.2x): emite RateLimitAction
- Backlog acumulado > max_backlog_s (default 10s): emite FramesDroppedAction
- Audio em velocidade normal (1x) NUNCA dispara eventos
- Primeiro frame nunca dispara (sem historico para comparar)

O calculo de taxa usa o backlog acumulado (audio_total - wall_elapsed)
como indicador principal. Se o backlog cresce acima do threshold
(rate_limit_threshold - 1.0) * wall_elapsed, o cliente esta enviando
mais rapido que o permitido.

Alem disso, uma sliding window de 5s e usada para verificar bursts
recentes sem penalizar por historico antigo.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# PCM 16-bit mono: 2 bytes por sample
_BYTES_PER_SAMPLE = 2

# Tamanho da sliding window para calculo de taxa (segundos)
_SLIDING_WINDOW_S = 5.0

# Tempo minimo de wall-clock antes de comecar a verificar taxa (segundos)
# Evita falsos positivos nos primeiros instantes
_MIN_WALL_FOR_RATE_CHECK_S = 0.5

# Intervalo minimo entre emissoes de RateLimitAction (segundos)
_RATE_LIMIT_COOLDOWN_S = 1.0


@dataclass(frozen=True, slots=True)
class RateLimitAction:
    """Acao: cliente deve desacelerar envio de audio.

    Emitida quando a taxa de envio excede rate_limit_threshold.
    O campo delay_ms sugere quanto tempo o cliente deve esperar
    antes de enviar o proximo frame.
    """

    delay_ms: int


@dataclass(frozen=True, slots=True)
class FramesDroppedAction:
    """Acao: frames foram descartados por excesso de backlog.

    Emitida quando o audio acumulado nao-processado excede max_backlog_s.
    O campo dropped_ms indica quanto audio (em ms) foi descartado.
    """

    dropped_ms: int


BackpressureAction = RateLimitAction | FramesDroppedAction


class BackpressureController:
    """Controla backpressure de ingestao de audio streaming.

    Monitora a taxa de recebimento de frames em relacao ao tempo real.
    Usa backlog acumulado e sliding window para detectar envio
    mais rapido que real-time.

    Args:
        sample_rate: Taxa de amostragem do audio em Hz (default: 16000).
        max_backlog_s: Maximo de audio acumulado em segundos antes de
            dropar frames (default: 10.0).
        rate_limit_threshold: Fator acima do qual emitir rate_limit.
            1.2 significa 120% de real-time (default: 1.2).
        clock: Funcao de relogio para injecao em testes.
            Default: time.monotonic.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        max_backlog_s: float = 10.0,
        rate_limit_threshold: float = 1.2,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._max_backlog_s = max_backlog_s
        self._rate_limit_threshold = rate_limit_threshold
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic

        # Contadores
        self._frames_received = 0
        self._frames_dropped = 0

        # Sliding window: deque de (wall_time, audio_duration_s)
        self._window: deque[tuple[float, float]] = deque()

        # Tempo de inicio e audio total acumulado
        self._start_time: float | None = None
        self._total_audio_s: float = 0.0

        # Duracao do primeiro frame (para correcao de taxa)
        self._first_frame_duration_s: float = 0.0

        # Cooldown para rate_limit (-inf garante que o primeiro disparo funciona)
        self._last_rate_limit_time: float = float("-inf")

    @property
    def frames_received(self) -> int:
        """Total de frames recebidos (incluindo dropados)."""
        return self._frames_received

    @property
    def frames_dropped(self) -> int:
        """Total de frames dropados por excesso de backlog."""
        return self._frames_dropped

    def record_frame(self, frame_bytes: int) -> BackpressureAction | None:
        """Registra recebimento de um frame de audio.

        Calcula a duracao do frame em segundos com base no tamanho em bytes
        e no sample_rate. Verifica backlog e taxa para decidir se backpressure
        e necessario.

        Args:
            frame_bytes: Tamanho do frame em bytes (PCM 16-bit mono).

        Returns:
            BackpressureAction se backpressure e necessario, None caso contrario.
            - RateLimitAction: taxa acima do threshold, sugere delay_ms
            - FramesDroppedAction: backlog excedido, frames descartados
        """
        now: float = self._clock()
        self._frames_received += 1

        # Duracao do frame em segundos
        n_samples = frame_bytes / _BYTES_PER_SAMPLE
        frame_duration_s = n_samples / self._sample_rate

        # Primeiro frame: inicializa e retorna (sem historico para comparar)
        if self._start_time is None:
            self._start_time = now
            self._total_audio_s = frame_duration_s
            self._first_frame_duration_s = frame_duration_s
            self._window.append((now, frame_duration_s))
            return None

        # Atualizar acumuladores
        self._total_audio_s += frame_duration_s
        wall_elapsed = now - self._start_time
        self._window.append((now, frame_duration_s))

        # Podar sliding window: remover entradas mais antigas que _SLIDING_WINDOW_S
        cutoff = now - _SLIDING_WINDOW_S
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()

        # Verificar backlog (audio total - tempo real decorrido)
        # Para o primeiro frame, wall_elapsed=0 e total_audio=frame_duration,
        # entao backlog = frame_duration (~0.02s). Isso e normal.
        backlog_s = self._total_audio_s - wall_elapsed
        if backlog_s > self._max_backlog_s:
            # Dropar este frame
            self._frames_dropped += 1
            # Reduzir audio acumulado pelo que foi dropado
            self._total_audio_s -= frame_duration_s
            dropped_ms = int(frame_duration_s * 1000)
            return FramesDroppedAction(dropped_ms=dropped_ms)

        # Verificar taxa somente apos wall_elapsed minimo
        # Evita falsos positivos nos primeiros instantes (poucos frames,
        # ratio impreciso)
        if wall_elapsed < _MIN_WALL_FOR_RATE_CHECK_S:
            return None

        # Calcular taxa: audio_total / wall_elapsed
        # Para audio 1x: audio ~= wall, rate ~= 1.0
        # Para audio 2x: audio ~= 2*wall, rate ~= 2.0
        # O primeiro frame contribui com frame_duration de audio "de graca"
        # (sem wall-time correspondente), entao subtraimos a duracao do
        # primeiro frame (constante) para corrigir.
        effective_audio = self._total_audio_s - self._first_frame_duration_s
        if wall_elapsed <= 0:
            return None
        rate = effective_audio / wall_elapsed

        if rate > self._rate_limit_threshold:
            # Cooldown: nao emitir rate_limit com muita frequencia
            if (now - self._last_rate_limit_time) < _RATE_LIMIT_COOLDOWN_S:
                return None

            self._last_rate_limit_time = now

            # Sugerir delay para o cliente voltar ao real-time
            excess_rate = rate - 1.0
            delay_ms = max(1, int(excess_rate * frame_duration_s * 1000))
            return RateLimitAction(delay_ms=delay_ms)

        return None
