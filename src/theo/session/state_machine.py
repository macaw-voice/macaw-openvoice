"""SessionStateMachine — maquina de estados da sessao de streaming STT.

Implementa 6 estados com transicoes validas, timeouts configuraveis por estado,
e callbacks on_enter/on_exit. Componente puro e sincrono — nao conhece gRPC,
WebSocket ou asyncio. O caller (StreamingSession) e responsavel por chamar
transition() e check_timeout() nos momentos corretos.

Estados:
    INIT -> ACTIVE -> SILENCE -> HOLD -> CLOSING -> CLOSED

Regras:
- CLOSED e terminal: nenhuma transicao e aceita a partir de CLOSED.
- Qualquer estado pode transitar para CLOSED (erro irrecuperavel).
- Transicoes invalidas levantam InvalidTransitionError.
- Timeouts sao verificados via check_timeout() (O(1), sem timers/tasks).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from Macaw._types import SessionState
from Macaw.exceptions import InvalidTransitionError

if TYPE_CHECKING:
    from collections.abc import Callable

# Transicoes validas: {estado_atual: {estados_alvo_permitidos}}
_VALID_TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.INIT: frozenset({SessionState.ACTIVE, SessionState.CLOSED}),
    SessionState.ACTIVE: frozenset(
        {SessionState.SILENCE, SessionState.CLOSING, SessionState.CLOSED}
    ),
    SessionState.SILENCE: frozenset(
        {SessionState.ACTIVE, SessionState.HOLD, SessionState.CLOSING, SessionState.CLOSED}
    ),
    SessionState.HOLD: frozenset({SessionState.ACTIVE, SessionState.CLOSING, SessionState.CLOSED}),
    SessionState.CLOSING: frozenset({SessionState.CLOSED}),
    SessionState.CLOSED: frozenset(),
}

# Timeouts: {estado -> estado_alvo_quando_expira}
_TIMEOUT_TARGETS: dict[SessionState, SessionState] = {
    SessionState.INIT: SessionState.CLOSED,
    SessionState.SILENCE: SessionState.HOLD,
    SessionState.HOLD: SessionState.CLOSING,
    SessionState.CLOSING: SessionState.CLOSED,
}


_MIN_TIMEOUT_S = 1.0


@dataclass(frozen=True, slots=True)
class SessionTimeouts:
    """Timeouts configuraveis por estado (em segundos).

    Defaults do PRD:
        INIT: 30s (sem audio -> CLOSED)
        SILENCE: 30s (sem fala -> HOLD)
        HOLD: 5min (silencio prolongado -> CLOSING)
        CLOSING: 2s (flush pendentes -> CLOSED)

    Raises:
        ValueError: Se qualquer timeout for menor que 1.0s.
    """

    init_timeout_s: float = 30.0
    silence_timeout_s: float = 30.0
    hold_timeout_s: float = 300.0
    closing_timeout_s: float = 2.0

    def __post_init__(self) -> None:
        for field_name in (
            "init_timeout_s",
            "silence_timeout_s",
            "hold_timeout_s",
            "closing_timeout_s",
        ):
            value = getattr(self, field_name)
            if value < _MIN_TIMEOUT_S:
                msg = f"Timeout '{field_name}' deve ser >= {_MIN_TIMEOUT_S}s, recebeu {value}s"
                raise ValueError(msg)

    def get_timeout_for_state(self, state: SessionState) -> float | None:
        """Retorna o timeout em segundos para o estado, ou None se nao tem timeout."""
        if state == SessionState.INIT:
            return self.init_timeout_s
        if state == SessionState.SILENCE:
            return self.silence_timeout_s
        if state == SessionState.HOLD:
            return self.hold_timeout_s
        if state == SessionState.CLOSING:
            return self.closing_timeout_s
        return None


def timeouts_from_configure_command(
    current: SessionTimeouts,
    *,
    silence_timeout_ms: int | None = None,
    hold_timeout_ms: int | None = None,
    max_segment_duration_ms: int | None = None,
) -> SessionTimeouts:
    """Cria SessionTimeouts atualizados a partir de campos do SessionConfigureCommand.

    Converte valores de milissegundos (protocolo WebSocket) para segundos (state machine).
    Campos None mantem o valor atual.

    Args:
        current: Timeouts atuais.
        silence_timeout_ms: Timeout de silencio em ms (None = manter atual).
        hold_timeout_ms: Timeout de hold em ms (None = manter atual).
        max_segment_duration_ms: Nao afeta timeouts da state machine (reservado para
            duracao maxima de segmento no Ring Buffer). Aceito mas ignorado.

    Returns:
        Novo SessionTimeouts com valores atualizados.

    Raises:
        ValueError: Se algum timeout convertido for menor que 1.0s.
    """
    return SessionTimeouts(
        init_timeout_s=current.init_timeout_s,
        silence_timeout_s=(
            silence_timeout_ms / 1000.0
            if silence_timeout_ms is not None
            else current.silence_timeout_s
        ),
        hold_timeout_s=(
            hold_timeout_ms / 1000.0 if hold_timeout_ms is not None else current.hold_timeout_s
        ),
        closing_timeout_s=current.closing_timeout_s,
    )


class SessionStateMachine:
    """Maquina de estados para sessao de streaming STT.

    Gerencia 6 estados com transicoes validas, timeouts por estado,
    e callbacks on_enter/on_exit.

    Args:
        timeouts: Timeouts configuraveis por estado.
        on_enter: Callbacks chamados ao ENTRAR em um estado.
        on_exit: Callbacks chamados ao SAIR de um estado.
        clock: Funcao que retorna timestamp monotonic (para testes deterministicos).
    """

    def __init__(
        self,
        timeouts: SessionTimeouts | None = None,
        on_enter: dict[SessionState, Callable[[], None]] | None = None,
        on_exit: dict[SessionState, Callable[[], None]] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._state = SessionState.INIT
        self._timeouts = timeouts or SessionTimeouts()
        self._on_enter = on_enter or {}
        self._on_exit = on_exit or {}
        self._clock = clock or time.monotonic
        self._state_entered_at = self._clock()

    @property
    def state(self) -> SessionState:
        """Estado atual da sessao."""
        return self._state

    @property
    def elapsed_in_state_ms(self) -> int:
        """Tempo (em milissegundos) que a sessao esta no estado atual."""
        elapsed_s = self._clock() - self._state_entered_at
        return int(elapsed_s * 1000)

    @property
    def timeouts(self) -> SessionTimeouts:
        """Timeouts configurados."""
        return self._timeouts

    def transition(self, target: SessionState) -> None:
        """Transita para o estado alvo.

        Args:
            target: Estado alvo da transicao.

        Raises:
            InvalidTransitionError: Se a transicao e invalida.
        """
        if target not in _VALID_TRANSITIONS[self._state]:
            raise InvalidTransitionError(self._state.value, target.value)

        previous = self._state

        # Callback on_exit do estado anterior
        exit_cb = self._on_exit.get(previous)
        if exit_cb is not None:
            exit_cb()

        # Transitar
        self._state = target
        self._state_entered_at = self._clock()

        # Callback on_enter do novo estado
        enter_cb = self._on_enter.get(target)
        if enter_cb is not None:
            enter_cb()

    def check_timeout(self) -> SessionState | None:
        """Verifica se o timeout do estado atual expirou.

        Returns:
            O estado alvo se timeout expirou, None se nao.
            O caller e responsavel por chamar transition() com o resultado.

        Complexidade: O(1) — apenas comparacao de elapsed vs timeout.
        """
        timeout_s = self._timeouts.get_timeout_for_state(self._state)
        if timeout_s is None:
            return None

        elapsed_s = self._clock() - self._state_entered_at
        if elapsed_s >= timeout_s:
            return _TIMEOUT_TARGETS.get(self._state)

        return None

    def update_timeouts(self, timeouts: SessionTimeouts) -> None:
        """Atualiza timeouts da state machine.

        Afeta o estado atual: se o timeout do estado atual mudou, o novo
        valor e considerado imediatamente na proxima chamada a check_timeout().

        Args:
            timeouts: Novos timeouts.
        """
        self._timeouts = timeouts
