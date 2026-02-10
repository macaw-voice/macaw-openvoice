"""LocalAgreement -- confirmacao de tokens entre passes para partial transcripts.

Para engines encoder-decoder (Whisper), partials nativos nao existem.
LocalAgreement compara output entre passes consecutivas: tokens que
concordam entre 2+ passes sao confirmados como partial; tokens
divergentes sao retidos ate a proxima pass.

Conceito inspirado no whisper-streaming (UFAL), implementacao propria.

Algoritmo:
    1. Recebe lista de tokens (palavras) de cada pass de inferencia.
    2. Compara posicao a posicao com a pass anterior.
    3. Tokens que concordam em min_confirm_passes passes consecutivas
       sao promovidos a confirmados (emitidos como transcript.partial).
    4. Tokens que divergem sao retidos (aguardam proxima pass).
    5. Tokens confirmados sao monotonicamente crescentes (nunca retraidos).
    6. Flush (VAD speech_end) emite todos os tokens como transcript.final.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AgreementResult:
    """Resultado de uma comparacao de agreement.

    Atributos:
        confirmed_text: Texto confirmado ate agora (pode ser emitido como partial).
        retained_text: Texto retido (aguardando proxima pass).
        confirmed_tokens: Lista de tokens confirmados.
        retained_tokens: Lista de tokens retidos.
        is_new_confirmation: True se novos tokens foram confirmados nesta pass.
    """

    confirmed_text: str
    retained_text: str
    confirmed_tokens: list[str] = field(default_factory=list)
    retained_tokens: list[str] = field(default_factory=list)
    is_new_confirmation: bool = False


class LocalAgreementPolicy:
    """Politica de confirmacao de tokens por agreement entre passes.

    Compara tokens de inferencia entre passes consecutivas. Tokens que
    concordam na mesma posicao em min_confirm_passes passes seguidas sao
    confirmados. Tokens confirmados sao monotonicamente crescentes.

    Uso tipico::

        policy = LocalAgreementPolicy(min_confirm_passes=2)

        # Pass 1: primeiros tokens do worker
        result = policy.process_pass(["hello", "how"])
        # result.confirmed_text == ""  (primeira pass, nada confirmado)

        # Pass 2: tokens concordam
        result = policy.process_pass(["hello", "how", "are"])
        # result.confirmed_text == "hello how"
        # result.retained_text == "are"

        # Flush (speech_end): emite tudo
        result = policy.flush()
        # result.confirmed_text == "hello how are"

    Args:
        min_confirm_passes: Passes minimas para confirmar token (default: 2).

    Raises:
        ValueError: Se min_confirm_passes < 1.
    """

    __slots__ = (
        "_confirmed_tokens",
        "_min_confirm_passes",
        "_pass_count",
        "_previous_tokens",
    )

    def __init__(self, min_confirm_passes: int = 2) -> None:
        if min_confirm_passes < 1:
            msg = f"min_confirm_passes deve ser >= 1, recebeu {min_confirm_passes}"
            raise ValueError(msg)
        self._min_confirm_passes = min_confirm_passes
        self._previous_tokens: list[str] = []
        self._confirmed_tokens: list[str] = []
        self._pass_count: int = 0

    @property
    def confirmed_text(self) -> str:
        """Texto confirmado ate agora."""
        return " ".join(self._confirmed_tokens) if self._confirmed_tokens else ""

    @property
    def pass_count(self) -> int:
        """Numero de passes processadas."""
        return self._pass_count

    def process_pass(self, tokens: list[str]) -> AgreementResult:
        """Processa uma nova pass de tokens do worker.

        Compara tokens com a pass anterior posicao a posicao.
        Tokens que concordam em min_confirm_passes passes consecutivas
        sao confirmados. Tokens ja confirmados nunca sao retraidos.

        Args:
            tokens: Lista de tokens (palavras) retornados pela engine.

        Returns:
            AgreementResult com tokens confirmados e retidos.
        """
        self._pass_count += 1

        if self._pass_count < self._min_confirm_passes:
            # Passes insuficientes: nada pode ser confirmado ainda
            self._previous_tokens = list(tokens)
            retained = tokens[len(self._confirmed_tokens) :]
            return AgreementResult(
                confirmed_text=self.confirmed_text,
                retained_text=" ".join(retained) if retained else "",
                confirmed_tokens=list(self._confirmed_tokens),
                retained_tokens=list(retained),
                is_new_confirmation=False,
            )

        # Comparar com pass anterior: encontrar prefixo que concorda
        # a partir do final dos tokens ja confirmados
        new_confirmed: list[str] = []
        confirmed_end = len(self._confirmed_tokens)
        prev = self._previous_tokens
        curr = tokens

        i = confirmed_end
        while i < len(prev) and i < len(curr):
            if prev[i] == curr[i]:
                new_confirmed.append(curr[i])
                i += 1
            else:
                break

        is_new = len(new_confirmed) > 0
        if is_new:
            self._confirmed_tokens.extend(new_confirmed)

        # Tokens apos os confirmados sao retidos
        retained = tokens[len(self._confirmed_tokens) :]

        self._previous_tokens = list(tokens)

        return AgreementResult(
            confirmed_text=self.confirmed_text,
            retained_text=" ".join(retained) if retained else "",
            confirmed_tokens=list(self._confirmed_tokens),
            retained_tokens=list(retained),
            is_new_confirmation=is_new,
        )

    def flush(self) -> AgreementResult:
        """Flush: emite TODOS os tokens (confirmados + retidos) como confirmados.

        Chamado ao receber VAD speech_end. Tudo vira transcript.final.
        Reseta o estado para o proximo segmento.

        Returns:
            AgreementResult com todos os tokens como confirmados.
        """
        all_tokens = list(self._confirmed_tokens)
        # Adicionar tokens retidos da pass anterior que nao foram confirmados
        if self._previous_tokens:
            remaining = self._previous_tokens[len(self._confirmed_tokens) :]
            all_tokens.extend(remaining)

        result = AgreementResult(
            confirmed_text=" ".join(all_tokens) if all_tokens else "",
            retained_text="",
            confirmed_tokens=list(all_tokens),
            retained_tokens=[],
            is_new_confirmation=len(all_tokens) > len(self._confirmed_tokens),
        )

        # Reset para proximo segmento
        self._previous_tokens = []
        self._confirmed_tokens = []
        self._pass_count = 0

        return result

    def reset(self) -> None:
        """Reseta o estado completamente (novo segmento de fala)."""
        self._previous_tokens = []
        self._confirmed_tokens = []
        self._pass_count = 0
