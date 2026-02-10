"""CrossSegmentContext — contexto entre segmentos para continuidade.

Armazena os ultimos N tokens (palavras) do transcript.final mais recente
como initial_prompt para o proximo segmento. Melhora continuidade em
palavras cortadas no limite de segmentos.

Aplicavel apenas a engines que suportam conditioning (Whisper).
Para CTC/streaming-native, o contexto e ignorado pelo worker.

Referencia: PRD secao RF-12 (Cross-Segment Context).
"""

from __future__ import annotations


class CrossSegmentContext:
    """Contexto cross-segment para conditioning do proximo segmento.

    Armazena os ultimos ``max_tokens`` palavras do transcript.final mais
    recente. Usado como ``initial_prompt`` na proxima inferencia do worker,
    melhorando continuidade em frases cortadas no limite de segmentos.

    O valor default de 224 tokens corresponde a metade do context window
    do Whisper (448 tokens), conforme especificado no PRD.

    Uso tipico:
        context = CrossSegmentContext(max_tokens=224)
        context.update("ola como posso ajudar")
        prompt = context.get_prompt()  # "ola como posso ajudar"
    """

    __slots__ = ("_max_tokens", "_text")

    def __init__(self, max_tokens: int = 224) -> None:
        self._max_tokens = max_tokens
        self._text: str | None = None

    def update(self, text: str) -> None:
        """Atualiza o contexto com o texto do transcript.final.

        Armazena as ultimas ``max_tokens`` palavras do texto fornecido.
        Se o texto tiver mais palavras que max_tokens, trunca do inicio
        (mantendo as palavras mais recentes).

        Args:
            text: Texto do transcript.final emitido ao cliente.
        """
        stripped = text.strip()
        if not stripped:
            self._text = None
            return

        words = stripped.split()
        if len(words) > self._max_tokens:
            words = words[-self._max_tokens :]

        self._text = " ".join(words)

    def get_prompt(self) -> str | None:
        """Retorna o contexto armazenado ou None se vazio.

        Returns:
            Texto das ultimas max_tokens palavras do transcript.final
            anterior, ou None se nenhum contexto foi registrado.
        """
        return self._text

    def reset(self) -> None:
        """Limpa o contexto armazenado."""
        self._text = None

    @property
    def context_text(self) -> str | None:
        """Alias para get_prompt(). Retorna o contexto ou None."""
        return self._text
