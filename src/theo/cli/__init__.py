"""CLI do Macaw OpenVoice.

Registra todos os comandos no grupo principal.
"""

from Macaw.cli.main import cli
from Macaw.cli.models import inspect, list_models
from Macaw.cli.ps import ps
from Macaw.cli.pull import pull
from Macaw.cli.remove import remove
from Macaw.cli.serve import serve
from Macaw.cli.transcribe import transcribe, translate

__all__ = [
    "cli",
    "inspect",
    "list_models",
    "ps",
    "pull",
    "remove",
    "serve",
    "transcribe",
    "translate",
]
