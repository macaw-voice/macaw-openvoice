"""Interface abstrata para backends STT.

Todo backend STT (Faster-Whisper, WeNet, Paraformer) deve implementar
esta interface para ser plugavel no runtime Macaw.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from Macaw._types import (
        BatchResult,
        EngineCapabilities,
        STTArchitecture,
        TranscriptSegment,
    )


class STTBackend(ABC):
    """Contrato que toda engine STT deve implementar.

    O runtime interage com engines exclusivamente atraves desta interface.
    Adicionar uma nova engine requer:
    1. Implementar STTBackend
    2. Criar manifesto Macaw.yaml
    3. Registrar no Model Registry
    Zero mudancas no runtime core.
    """

    @property
    @abstractmethod
    def architecture(self) -> STTArchitecture:
        """Arquitetura do modelo (encoder-decoder, ctc, streaming-native).

        Determina como o runtime adapta o pipeline de streaming.
        """
        ...

    @abstractmethod
    async def load(self, model_path: str, config: dict[str, object]) -> None:
        """Carrega o modelo em memoria.

        Args:
            model_path: Caminho para os arquivos do modelo.
            config: engine_config do manifesto Macaw.yaml.

        Raises:
            ModelLoadError: Se o modelo nao puder ser carregado.
        """
        ...

    @abstractmethod
    async def capabilities(self) -> EngineCapabilities:
        """Capabilities da engine em runtime.

        Pode diferir do manifesto se a engine descobrir capabilities
        adicionais apos load.
        """
        ...

    @abstractmethod
    async def transcribe_file(
        self,
        audio_data: bytes,
        language: str | None = None,
        initial_prompt: str | None = None,
        hot_words: list[str] | None = None,
        temperature: float = 0.0,
        word_timestamps: bool = False,
    ) -> BatchResult:
        """Transcreve audio completo (batch).

        Args:
            audio_data: Audio PCM 16-bit, 16kHz, mono (ja preprocessado).
            language: Codigo ISO 639-1, "auto", ou "mixed".
            initial_prompt: Contexto para guiar transcricao.
            hot_words: Palavras para keyword boosting.
            temperature: Temperatura de sampling (0.0-1.0).
            word_timestamps: Se True, retorna timestamps por palavra.

        Returns:
            BatchResult com texto, idioma, duracao e segmentos.
        """
        ...

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        language: str | None = None,
        initial_prompt: str | None = None,
        hot_words: list[str] | None = None,
    ) -> AsyncIterator[TranscriptSegment]:
        """Transcreve audio em streaming.

        Recebe chunks de audio PCM 16-bit, 16kHz, mono (ja preprocessado
        pelo Audio Preprocessing Pipeline do runtime).

        Para encoder-decoder: runtime usa LocalAgreement para partials.
        Para CTC: engine produz partials nativos frame-by-frame.
        Para streaming-native: engine gerencia estado interno.

        Args:
            audio_chunks: Iterator assincrono de chunks PCM.
            language: Codigo ISO 639-1, "auto", ou "mixed".
            initial_prompt: Contexto do segmento anterior.
            hot_words: Palavras para keyword boosting.

        Yields:
            TranscriptSegment (partial e final).
        """
        ...

    @abstractmethod
    async def unload(self) -> None:
        """Descarrega o modelo da memoria.

        Libera recursos (GPU memory, buffers). Apos unload, load()
        deve ser chamado novamente antes de transcribe.
        """
        ...

    @abstractmethod
    async def health(self) -> dict[str, str]:
        """Status do backend.

        Returns:
            Dict com pelo menos {"status": "ok"|"loading"|"error"}.
        """
        ...
