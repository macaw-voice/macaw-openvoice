"""Model Registry — descobre e fornece manifestos de modelos instalados."""

from __future__ import annotations

from pathlib import Path

from Macaw.config.manifest import ModelManifest
from Macaw.exceptions import ModelNotFoundError
from Macaw.logging import get_logger

logger = get_logger("registry")


class ModelRegistry:
    """Descobre e fornece manifestos de modelos instalados.

    Escaneia um diretorio de modelos buscando Macaw.yaml em cada
    subdiretorio. Nao gerencia lifecycle (load/unload) — apenas
    informa quais modelos existem e suas configuracoes.
    """

    def __init__(self, models_dir: str | Path) -> None:
        self._models_dir = Path(models_dir)
        self._manifests: dict[str, ModelManifest] = {}
        self._model_paths: dict[str, Path] = {}

    async def scan(self) -> None:
        """Escaneia models_dir e carrega todos os manifestos.

        Para cada subdiretorio que contem Macaw.yaml:
        1. Parseia com ModelManifest.from_yaml_path()
        2. Indexa por manifest.name (nao pelo nome do diretorio)
        3. Ignora subdiretorios sem Macaw.yaml (log debug)
        4. Ignora manifestos invalidos (log error, nao crash)
        """
        self._manifests.clear()
        self._model_paths.clear()

        if not self._models_dir.exists():
            logger.warning("models_dir_not_found", path=str(self._models_dir))
            return

        for subdir in sorted(self._models_dir.iterdir()):
            if not subdir.is_dir():
                continue

            manifest_path = subdir / "Macaw.yaml"
            if not manifest_path.exists():
                logger.debug("no_manifest", dir=str(subdir))
                continue

            try:
                manifest = ModelManifest.from_yaml_path(manifest_path)
                self._manifests[manifest.name] = manifest
                self._model_paths[manifest.name] = subdir
                logger.info("model_found", name=manifest.name, engine=manifest.engine)
            except Exception as exc:
                logger.error("manifest_error", path=str(manifest_path), error=str(exc))

    def get_manifest(self, model_name: str) -> ModelManifest:
        """Retorna manifesto do modelo.

        Raises:
            ModelNotFoundError: Se modelo nao encontrado.
        """
        manifest = self._manifests.get(model_name)
        if manifest is None:
            raise ModelNotFoundError(model_name)
        return manifest

    def list_models(self) -> list[ModelManifest]:
        """Retorna lista de todos os modelos instalados."""
        return list(self._manifests.values())

    def has_model(self, model_name: str) -> bool:
        """Verifica se modelo existe no registry."""
        return model_name in self._manifests

    def get_model_path(self, model_name: str) -> Path:
        """Retorna caminho do diretorio do modelo.

        Raises:
            ModelNotFoundError: Se modelo nao encontrado.
        """
        path = self._model_paths.get(model_name)
        if path is None:
            raise ModelNotFoundError(model_name)
        return path
