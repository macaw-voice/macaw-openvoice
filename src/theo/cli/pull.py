"""Comando `Macaw pull` — baixa modelos do HuggingFace Hub."""

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
    help="Diretorio para instalar modelos.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Sobrescreve modelo existente.",
)
def pull(model_name: str, models_dir: str, force: bool) -> None:
    """Baixa um modelo do HuggingFace Hub.

    Modelos disponiveis: faster-whisper-tiny, faster-whisper-small,
    faster-whisper-medium, faster-whisper-large-v3, distil-whisper-large-v3,
    kokoro-v1.

    Exemplo: Macaw pull faster-whisper-tiny
    """
    from pathlib import Path

    from Macaw.registry.catalog import ModelCatalog
    from Macaw.registry.downloader import ModelDownloader

    # Carregar catalogo
    catalog = ModelCatalog()
    try:
        catalog.load()
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Erro ao carregar catalogo: {e}", err=True)
        sys.exit(1)

    # Verificar se modelo existe no catalogo
    entry = catalog.get(model_name)
    if entry is None:
        click.echo(f"Erro: modelo '{model_name}' nao encontrado no catalogo.", err=True)
        click.echo("", err=True)
        click.echo("Modelos disponiveis:", err=True)
        for m in catalog.list_models():
            click.echo(f"  {m.name:<30} {m.description}", err=True)
        sys.exit(1)

    # Download
    downloader = ModelDownloader(Path(models_dir).expanduser())

    if downloader.is_installed(model_name) and not force:
        click.echo(f"Modelo '{model_name}' ja esta instalado.")
        click.echo("Use --force para reinstalar.")
        return

    click.echo(f"Baixando {model_name} de {entry.repo}...")

    try:
        model_dir = downloader.download(entry, force=force)
    except RuntimeError as e:
        click.echo(f"Erro: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Erro ao baixar modelo: {e}", err=True)
        sys.exit(1)

    click.echo(f"Modelo instalado em {model_dir}")
    click.echo("Execute 'Macaw serve' para iniciar o servidor.")
