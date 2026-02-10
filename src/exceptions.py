"""Exceptions tipadas do Macaw OpenVoice.

Hierarquia:
    MacawError (base)
    +-- ConfigError
    |   +-- ManifestParseError
    |   +-- ManifestValidationError
    +-- ModelError
    |   +-- ModelNotFoundError
    |   +-- ModelLoadError
    +-- WorkerError
    |   +-- WorkerCrashError
    |   +-- WorkerTimeoutError
    |   +-- WorkerUnavailableError
    +-- AudioError
    |   +-- AudioFormatError
    |   +-- AudioTooLargeError
    +-- SessionError
    |   +-- SessionNotFoundError
    |   +-- SessionClosedError
    |   +-- InvalidTransitionError
    |   +-- BufferOverrunError
    +-- TTSError
    |   +-- TTSSynthesisError
    +-- InvalidRequestError
"""

from __future__ import annotations


class MacawError(Exception):
    """Base para todas as exceptions do Macaw OpenVoice."""


# --- Configuracao ---


class ConfigError(MacawError):
    """Erro de configuracao do runtime."""


class ManifestParseError(ConfigError):
    """Falha ao parsear arquivo Macaw.yaml."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Falha ao parsear manifesto '{path}': {reason}")


class ManifestValidationError(ConfigError):
    """Manifesto Macaw.yaml invalido (campos obrigatorios faltando, tipos errados)."""

    def __init__(self, path: str, errors: list[str]) -> None:
        self.path = path
        self.errors = errors
        detail = "; ".join(errors)
        super().__init__(f"Manifesto '{path}' invalido: {detail}")


# --- Modelo ---


class ModelError(MacawError):
    """Erro relacionado a modelos."""


class ModelNotFoundError(ModelError):
    """Modelo nao encontrado no registry."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(f"Modelo '{model_name}' nao encontrado no registry")


class ModelLoadError(ModelError):
    """Falha ao carregar modelo em memoria."""

    def __init__(self, model_name: str, reason: str) -> None:
        self.model_name = model_name
        self.reason = reason
        super().__init__(f"Falha ao carregar modelo '{model_name}': {reason}")


# --- Worker ---


class WorkerError(MacawError):
    """Erro relacionado a workers (subprocessos gRPC)."""


class WorkerCrashError(WorkerError):
    """Worker crashou durante operacao."""

    def __init__(self, worker_id: str, exit_code: int | None = None) -> None:
        self.worker_id = worker_id
        self.exit_code = exit_code
        msg = f"Worker '{worker_id}' crashou"
        if exit_code is not None:
            msg += f" (exit code: {exit_code})"
        super().__init__(msg)


class WorkerTimeoutError(WorkerError):
    """Worker nao respondeu dentro do timeout."""

    def __init__(self, worker_id: str, timeout_seconds: float) -> None:
        self.worker_id = worker_id
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Worker '{worker_id}' nao respondeu em {timeout_seconds}s")


class WorkerUnavailableError(WorkerError):
    """Nenhum worker disponivel para atender a request."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(f"Nenhum worker disponivel para modelo '{model_name}'")


# --- Audio ---


class AudioError(MacawError):
    """Erro relacionado a processamento de audio."""


class AudioFormatError(AudioError):
    """Formato de audio nao suportado ou invalido."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Formato de audio invalido: {detail}")


class AudioTooLargeError(AudioError):
    """Arquivo de audio excede o limite permitido."""

    def __init__(self, size_bytes: int, max_bytes: int) -> None:
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes
        size_mb = size_bytes / (1024 * 1024)
        max_mb = max_bytes / (1024 * 1024)
        super().__init__(f"Arquivo de audio ({size_mb:.1f}MB) excede limite de {max_mb:.1f}MB")


# --- Sessao ---


class SessionError(MacawError):
    """Erro relacionado a sessoes de streaming."""


class SessionNotFoundError(SessionError):
    """Sessao nao encontrada."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Sessao '{session_id}' nao encontrada")


class SessionClosedError(SessionError):
    """Operacao tentada em sessao ja fechada."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Sessao '{session_id}' ja esta fechada")


class InvalidTransitionError(SessionError):
    """Transicao de estado invalida na maquina de estados da sessao."""

    def __init__(self, from_state: str, to_state: str) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Transicao invalida: {from_state} -> {to_state}")


class BufferOverrunError(SessionError):
    """Tentativa de leitura de dados ja sobrescritos ou alem do escrito no ring buffer."""


# --- Request ---


class InvalidRequestError(MacawError):
    """Parametro de request invalido."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


# --- TTS ---


class TTSError(MacawError):
    """Erro relacionado a sintese de voz (TTS)."""


class TTSSynthesisError(TTSError):
    """Falha durante sintese de voz."""

    def __init__(self, model_name: str, reason: str) -> None:
        self.model_name = model_name
        self.reason = reason
        super().__init__(f"Falha na sintese TTS com modelo '{model_name}': {reason}")
