"""Download de modelos do HuggingFace Hub.

Usa a biblioteca huggingface_hub para download de repositorios de modelos
com progress bar e validacao de manifesto apos copia.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from Macaw.config.manifest import ModelManifest
from Macaw.logging import get_logger

if TYPE_CHECKING:
    from Macaw.registry.catalog import CatalogEntry

logger = get_logger("registry.downloader")

_DEFAULT_MODELS_DIR = Path.home() / ".Macaw" / "models"


class ModelDownloader:
    """Baixa modelos do HuggingFace Hub para o diretorio local.

    Fluxo:
    1. Cria diretorio do modelo em models_dir/<model_name>/
    2. Baixa repositorio completo do HuggingFace Hub via snapshot_download
    3. Gera Macaw.yaml a partir do manifesto embutido no catalogo
    4. Valida manifesto apos geracao
    """

    def __init__(self, models_dir: str | Path | None = None) -> None:
        self._models_dir = Path(models_dir) if models_dir else _DEFAULT_MODELS_DIR

    @property
    def models_dir(self) -> Path:
        """Diretorio base de modelos."""
        return self._models_dir

    def is_installed(self, model_name: str) -> bool:
        """Verifica se modelo ja esta instalado."""
        model_dir = self._models_dir / model_name
        manifest_path = model_dir / "Macaw.yaml"
        return manifest_path.exists()

    def download(
        self,
        entry: CatalogEntry,
        *,
        force: bool = False,
    ) -> Path:
        """Baixa modelo do HuggingFace Hub.

        Args:
            entry: Entrada do catalogo com repositorio e manifesto.
            force: Se True, sobrescreve modelo existente.

        Returns:
            Path do diretorio do modelo instalado.

        Raises:
            RuntimeError: Se huggingface_hub nao esta instalado.
            FileExistsError: Se modelo ja esta instalado e force=False.
        """
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            msg = "huggingface_hub nao esta instalado. Instale com: pip install huggingface_hub"
            raise RuntimeError(msg) from None

        model_dir = self._models_dir / entry.name

        if model_dir.exists() and not force:
            manifest_path = model_dir / "Macaw.yaml"
            if manifest_path.exists():
                msg = (
                    f"Modelo '{entry.name}' ja esta instalado em {model_dir}. "
                    f"Use --force para reinstalar."
                )
                raise FileExistsError(msg)

        # Cria diretorio pai
        self._models_dir.mkdir(parents=True, exist_ok=True)

        # Limpa diretorio existente se force
        if model_dir.exists() and force:
            shutil.rmtree(model_dir)

        logger.info(
            "download_starting",
            model=entry.name,
            repo=entry.repo,
            target=str(model_dir),
        )

        # Download via HuggingFace Hub
        downloaded_path = snapshot_download(
            repo_id=entry.repo,
            local_dir=str(model_dir),
        )

        logger.info("download_complete", model=entry.name, path=downloaded_path)

        # Gera Macaw.yaml a partir do manifesto do catalogo
        self._write_manifest(model_dir, entry)

        # Valida manifesto gerado
        manifest_path = model_dir / "Macaw.yaml"
        ModelManifest.from_yaml_path(manifest_path)

        logger.info("manifest_validated", model=entry.name)

        return model_dir

    def remove(self, model_name: str) -> bool:
        """Remove modelo instalado.

        Args:
            model_name: Nome do modelo a remover.

        Returns:
            True se removido, False se nao existia.
        """
        model_dir = self._models_dir / model_name
        if not model_dir.exists():
            return False

        shutil.rmtree(model_dir)
        logger.info("model_removed", model=model_name, path=str(model_dir))
        return True

    def _write_manifest(self, model_dir: Path, entry: CatalogEntry) -> None:
        """Escreve Macaw.yaml no diretorio do modelo."""
        manifest_data = entry.manifest
        if not manifest_data:
            msg = f"Catalogo sem manifesto para modelo '{entry.name}'"
            raise ValueError(msg)

        manifest_path = model_dir / "Macaw.yaml"
        manifest_path.write_text(
            yaml.dump(manifest_data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        logger.info("manifest_written", model=entry.name, path=str(manifest_path))
