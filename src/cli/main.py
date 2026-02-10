"""Grupo principal de comandos CLI do Macaw OpenVoice."""

from __future__ import annotations

import click

import Macaw


@click.group()
@click.version_option(version=Macaw.__version__, prog_name="Macaw")
def cli() -> None:
    """Macaw OpenVoice — Runtime unificado de voz (STT + TTS)."""
