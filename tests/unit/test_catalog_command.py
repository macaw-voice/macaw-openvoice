"""Tests for `macaw catalog` command."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from click.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

from macaw.cli import cli
from macaw.registry.catalog import CatalogEntry


def _make_entries(count: int) -> list[CatalogEntry]:
    """Create dummy catalog entries for testing."""
    entries: list[CatalogEntry] = []
    for i in range(count):
        entries.append(
            CatalogEntry(
                name=f"model-{i}",
                repo=f"org/model-{i}",
                engine="faster-whisper" if i % 2 == 0 else "kokoro",
                model_type="stt" if i % 2 == 0 else "tts",
                architecture="encoder-decoder" if i % 2 == 0 else None,
                description=f"Description for model {i}",
            )
        )
    return entries


class TestCatalogCommand:
    def test_catalog_lists_models(self) -> None:
        entries = _make_entries(2)

        with patch("macaw.registry.catalog.ModelCatalog") as mock_cls:
            instance = mock_cls.return_value
            instance.list_models.return_value = entries

            runner = CliRunner()
            result = runner.invoke(cli, ["catalog"])

        assert result.exit_code == 0
        assert "model-0" in result.output
        assert "model-1" in result.output
        assert "faster-whisper" in result.output
        assert "kokoro" in result.output
        assert "stt" in result.output
        assert "tts" in result.output
        assert "Description for model 0" in result.output
        assert "Description for model 1" in result.output
        assert "NAME" in result.output
        assert "TYPE" in result.output
        assert "ENGINE" in result.output
        assert "DESCRIPTION" in result.output
        assert "macaw pull <name>" in result.output

    def test_catalog_empty(self) -> None:
        with patch("macaw.registry.catalog.ModelCatalog") as mock_cls:
            instance = mock_cls.return_value
            instance.list_models.return_value = []

            runner = CliRunner()
            result = runner.invoke(cli, ["catalog"])

        assert result.exit_code == 0
        assert "No models available" in result.output

    def test_catalog_load_failure(self, tmp_path: Path) -> None:
        with patch("macaw.registry.catalog.ModelCatalog") as mock_cls:
            instance = mock_cls.return_value
            instance.load.side_effect = FileNotFoundError("Catalog not found: missing.yaml")

            runner = CliRunner()
            result = runner.invoke(cli, ["catalog"])

        assert result.exit_code != 0
        assert "Failed to load catalog" in result.output
