"""Comando `Macaw remove` — remove modelo instalado."""

from __future__ import annotations

import sys

import click

from Macaw.cli.main import cli
from Macaw.cli.serve import DEFAULT_MODELS_DIR


@cli.command()
@click.argument("model_name")
@click.option(
    "--models-dir",
    default=DEFAULT_MODELS_DIR,
    show_default=True,
    help="Diretorio com modelos instalados.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Confirma remocao sem perguntar.",
)
def remove(model_name: str, models_dir: str, yes: bool) -> None:
    """Remove um modelo instalado.

    Exemplo: Macaw remove faster-whisper-tiny
    """
    from pathlib import Path

    from Macaw.registry.downloader import ModelDownloader

    downloader = ModelDownloader(Path(models_dir).expanduser())

    if not downloader.is_installed(model_name):
        click.echo(f"Erro: modelo '{model_name}' nao esta instalado.", err=True)
        sys.exit(1)

    if not yes and not click.confirm(f"Remover modelo '{model_name}'?"):
        click.echo("Cancelado.")
        return

    removed = downloader.remove(model_name)
    if removed:
        click.echo(f"Modelo '{model_name}' removido.")
    else:
        click.echo(f"Erro ao remover modelo '{model_name}'.", err=True)
        sys.exit(1)
