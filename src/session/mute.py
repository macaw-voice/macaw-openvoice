"""MuteController — coordena mute-on-speak para Full-Duplex STT+TTS.

Quando TTS esta ativo (bot falando), o STT deve ser silenciado para nao
transcrever o audio do proprio bot. O MuteController gerencia essa flag
e coordena com a StreamingSession.

Operacoes sao idempotentes: mute() quando ja muted e no-op, e vice-versa.

Lifecycle tipico:
    1. TTS worker comeca a produzir audio
    2. Handler chama mute_controller.mute() -> StreamingSession silencia
    3. TTS termina (ou e cancelado, ou worker crashar)
    4. Handler chama mute_controller.unmute() -> StreamingSession retoma

Garantia: unmute DEVE acontecer em try/finally para prevenir mute
permanente em caso de erro no fluxo TTS.
"""

from __future__ import annotations

from Macaw.logging import get_logger

logger = get_logger("session.mute")


class MuteController:
    """Controla mute-on-speak para uma sessao Full-Duplex.

    Thread-safe nao e necessario: tudo roda no mesmo event loop asyncio.
    Idempotente: mute/unmute duplicados sao no-op.

    Args:
        session_id: ID da sessao para logging.
    """

    def __init__(self, session_id: str = "") -> None:
        self._muted = False
        self._session_id = session_id

    @property
    def is_muted(self) -> bool:
        """True se o STT esta silenciado (TTS ativo)."""
        return self._muted

    def mute(self) -> None:
        """Silencia o STT. Idempotente: no-op se ja muted."""
        if self._muted:
            return
        self._muted = True
        logger.debug(
            "stt_muted",
            session_id=self._session_id,
        )

    def unmute(self) -> None:
        """Retoma o STT. Idempotente: no-op se ja unmuted."""
        if not self._muted:
            return
        self._muted = False
        logger.debug(
            "stt_unmuted",
            session_id=self._session_id,
        )
