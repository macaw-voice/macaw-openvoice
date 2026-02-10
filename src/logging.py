"""Structured logging para o Macaw OpenVoice.

Usa structlog com stdlib logging como backend. Dois formatos:
- console: legivel para desenvolvimento (default)
- json: estruturado para producao
"""

from __future__ import annotations

import logging
import os

import structlog

_configured = False


def configure_logging(
    log_format: str | None = None,
    level: str | None = None,
) -> None:
    """Configura logging estruturado para o runtime.

    Idempotente — chamadas subsequentes sao ignoradas.

    Args:
        log_format: "json" ou "console". Default via Macaw_LOG_FORMAT env ou "console".
        level: Nivel de log (DEBUG, INFO, WARNING, ERROR). Default via Macaw_LOG_LEVEL env ou "INFO".
    """
    global _configured
    if _configured:
        return

    resolved_format = log_format or os.environ.get("Macaw_LOG_FORMAT", "console")
    resolved_level = level or os.environ.get("Macaw_LOG_LEVEL", "INFO")

    shared_processors: list[structlog.types.Processor] = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
    ]

    if resolved_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, resolved_level.upper(), logging.INFO))

    _configured = True


def get_logger(component: str) -> structlog.stdlib.BoundLogger:
    """Retorna logger com contexto de componente.

    Args:
        component: Nome do componente (ex: "worker.stt", "session_manager").

    Returns:
        BoundLogger com campo component vinculado.
    """
    configure_logging()
    return structlog.get_logger().bind(component=component)  # type: ignore[no-any-return]
