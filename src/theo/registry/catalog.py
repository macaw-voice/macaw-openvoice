"""Catalogo de modelos oficiais do Macaw OpenVoice.

Le o catalogo declarativo (catalog.yaml) com modelos disponiveis para download
via HuggingFace Hub. Cada entrada contem repositorio, engine, tipo e manifesto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from Macaw.logging import get_logger

logger = get_logger("registry.catalog")

_CATALOG_PATH = Path(__file__).parent / "catalog.yaml"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """Entrada de modelo no catalogo."""

    name: str
    repo: str
    engine: str
    model_type: str
    architecture: str | None = None
    description: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)


class ModelCatalog:
    """Catalogo de modelos oficiais disponiveis para download.

    Le catalog.yaml e fornece lookup por nome de modelo.
    """

    def __init__(self, catalog_path: str | Path | None = None) -> None:
        self._path = Path(catalog_path) if catalog_path else _CATALOG_PATH
        self._entries: dict[str, CatalogEntry] = {}

    def load(self) -> None:
        """Carrega catalogo do arquivo YAML."""
        if not self._path.exists():
            msg = f"Catalogo nao encontrado: {self._path}"
            raise FileNotFoundError(msg)

        raw = self._path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)

        if not isinstance(data, dict) or "models" not in data:
            msg = f"Catalogo invalido: {self._path} (campo 'models' ausente)"
            raise ValueError(msg)

        models = data["models"]
        if not isinstance(models, dict):
            msg = f"Catalogo invalido: {self._path} ('models' deve ser mapeamento)"
            raise ValueError(msg)

        self._entries.clear()
        for name, info in models.items():
            if not isinstance(info, dict):
                logger.warning("catalog_entry_invalid", name=name)
                continue

            entry = CatalogEntry(
                name=str(name),
                repo=str(info.get("repo", "")),
                engine=str(info.get("engine", "")),
                model_type=str(info.get("type", "")),
                architecture=info.get("architecture"),
                description=str(info.get("description", "")),
                manifest=info.get("manifest", {}),
            )
            self._entries[name] = entry

        logger.info("catalog_loaded", models_count=len(self._entries))

    def get(self, model_name: str) -> CatalogEntry | None:
        """Retorna entrada do catalogo por nome, ou None se nao encontrada."""
        return self._entries.get(model_name)

    def list_models(self) -> list[CatalogEntry]:
        """Retorna todas as entradas do catalogo."""
        return list(self._entries.values())

    def has_model(self, model_name: str) -> bool:
        """Verifica se modelo existe no catalogo."""
        return model_name in self._entries
