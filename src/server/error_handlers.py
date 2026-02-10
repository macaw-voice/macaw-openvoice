"""Exception handlers HTTP para o FastAPI.

Mapeia exceptions tipadas do Macaw para respostas HTTP com status codes corretos.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

from Macaw.exceptions import (
    AudioFormatError,
    AudioTooLargeError,
    InvalidRequestError,
    ModelNotFoundError,
    MacawError,
    WorkerCrashError,
    WorkerTimeoutError,
    WorkerUnavailableError,
)
from Macaw.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = get_logger("server.errors")


def _error_response(status_code: int, message: str, error_type: str, code: str) -> JSONResponse:
    """Cria resposta de erro no formato compativel com OpenAI."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "code": code,
            }
        },
    )


def _get_request_id(request: Request) -> str | None:
    """Extrai request_id do request state, se disponivel."""
    return getattr(request.state, "request_id", None)


async def _handle_model_not_found(request: Request, exc: ModelNotFoundError) -> JSONResponse:
    logger.warning(
        "model_not_found",
        model_name=exc.model_name,
        request_id=_get_request_id(request),
    )
    return _error_response(404, str(exc), "model_not_found_error", "model_not_found")


async def _handle_invalid_request(request: Request, exc: InvalidRequestError) -> JSONResponse:
    logger.warning(
        "invalid_request",
        detail=exc.detail,
        request_id=_get_request_id(request),
    )
    return _error_response(400, str(exc), "invalid_request_error", "invalid_request")


async def _handle_audio_format_error(request: Request, exc: AudioFormatError) -> JSONResponse:
    logger.warning(
        "audio_format_error",
        detail=exc.detail,
        request_id=_get_request_id(request),
    )
    return _error_response(400, str(exc), "audio_format_error", "invalid_audio")


async def _handle_audio_too_large(request: Request, exc: AudioTooLargeError) -> JSONResponse:
    logger.warning(
        "audio_too_large",
        size_bytes=exc.size_bytes,
        max_bytes=exc.max_bytes,
        request_id=_get_request_id(request),
    )
    return _error_response(413, str(exc), "audio_too_large_error", "file_too_large")


async def _handle_worker_unavailable(
    request: Request, exc: WorkerUnavailableError
) -> JSONResponse:
    logger.error(
        "worker_unavailable",
        model_name=exc.model_name,
        request_id=_get_request_id(request),
    )
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "message": str(exc),
                "type": "worker_unavailable_error",
                "code": "service_unavailable",
            }
        },
        headers={"Retry-After": "5"},
    )


async def _handle_worker_timeout(request: Request, exc: WorkerTimeoutError) -> JSONResponse:
    logger.error(
        "worker_timeout",
        worker_id=exc.worker_id,
        timeout_seconds=exc.timeout_seconds,
        request_id=_get_request_id(request),
    )
    return _error_response(
        504,
        f"Worker nao respondeu em {exc.timeout_seconds:.0f}s",
        "worker_timeout_error",
        "gateway_timeout",
    )


async def _handle_worker_crash(request: Request, exc: WorkerCrashError) -> JSONResponse:
    logger.error(
        "worker_crash",
        worker_id=exc.worker_id,
        exit_code=exc.exit_code,
        request_id=_get_request_id(request),
    )
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "message": "Worker de inferencia falhou. Tente novamente.",
                "type": "worker_crash_error",
                "code": "bad_gateway",
            }
        },
        headers={"Retry-After": "5"},
    )


async def _handle_Macaw_error(request: Request, exc: MacawError) -> JSONResponse:
    logger.error(
        "unhandled_Macaw_error",
        error=str(exc),
        error_type=type(exc).__name__,
        request_id=_get_request_id(request),
        exc_info=True,
    )
    return _error_response(500, "Erro interno do servidor", "internal_error", "internal_error")


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unexpected_error",
        error=str(exc),
        error_type=type(exc).__name__,
        request_id=_get_request_id(request),
        exc_info=True,
    )
    return _error_response(500, "Erro interno do servidor", "internal_error", "internal_error")


def register_error_handlers(app: FastAPI) -> None:
    """Registra todos os exception handlers no FastAPI app."""
    app.add_exception_handler(InvalidRequestError, _handle_invalid_request)
    app.add_exception_handler(ModelNotFoundError, _handle_model_not_found)
    app.add_exception_handler(AudioFormatError, _handle_audio_format_error)
    app.add_exception_handler(AudioTooLargeError, _handle_audio_too_large)
    app.add_exception_handler(WorkerUnavailableError, _handle_worker_unavailable)
    app.add_exception_handler(WorkerTimeoutError, _handle_worker_timeout)
    app.add_exception_handler(WorkerCrashError, _handle_worker_crash)
    app.add_exception_handler(MacawError, _handle_Macaw_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
