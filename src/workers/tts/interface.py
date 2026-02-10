"""Interface abstrata para backends TTS.

Todo backend TTS (Kokoro, Piper) deve implementar esta interface
para ser plugavel no runtime Macaw.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from Macaw._types import VoiceInfo


class TTSBackend(ABC):
    """Contrato que toda engine TTS deve implementar.

    O runtime interage com engines TTS exclusivamente atraves desta interface.
    Adicionar uma nova engine requer:
    1. Implementar TTSBackend
    2. Criar manifesto Macaw.yaml com type: tts
    3. Registrar na factory _create_backend()
    Zero mudancas no runtime core.

    A diferenca fundamental em relacao a STTBackend e que synthesize()
    retorna um AsyncIterator de chunks de audio (streaming), permitindo
    TTS com baixo TTFB — o primeiro chunk pode ser enviado ao cliente
    antes de toda a sintese estar pronta.
    """

    @abstractmethod
    async def load(self, model_path: str, config: dict[str, object]) -> None:
        """Carrega o modelo TTS em memoria.

        Args:
            model_path: Caminho para os arquivos do modelo.
            config: engine_config do manifesto Macaw.yaml.

        Raises:
            ModelLoadError: Se o modelo nao puder ser carregado.
        """
        ...

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str = "default",
        *,
        sample_rate: int = 24000,
        speed: float = 1.0,
    ) -> AsyncIterator[bytes]:
        """Sintetiza texto em audio (streaming de chunks PCM).

        Retorna chunks de audio PCM 16-bit a medida que a engine sintetiza.
        Isso permite TTS streaming com baixo TTFB — o primeiro chunk
        pode estar pronto em <50ms para engines rapidas.

        Args:
            text: Texto a ser sintetizado.
            voice: Identificador da voz (default: "default").
            sample_rate: Taxa de amostragem do audio de saida.
            speed: Velocidade da sintese (0.25-4.0, default 1.0).

        Yields:
            Chunks de audio PCM 16-bit.

        Raises:
            TTSSynthesisError: Se a sintese falhar.
        """
        ...

    @abstractmethod
    async def voices(self) -> list[VoiceInfo]:
        """Lista vozes disponiveis no modelo.

        Returns:
            Lista de VoiceInfo com informacoes de cada voz.
        """
        ...

    @abstractmethod
    async def unload(self) -> None:
        """Descarrega o modelo TTS da memoria.

        Libera recursos (GPU memory, buffers). Apos unload, load()
        deve ser chamado novamente antes de synthesize.
        """
        ...

    @abstractmethod
    async def health(self) -> dict[str, str]:
        """Status do backend TTS.

        Returns:
            Dict com pelo menos {"status": "ok"|"loading"|"error"}.
        """
        ...
