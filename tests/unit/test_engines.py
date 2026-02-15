"""Tests for engine availability checks in `macaw.engines`."""

from __future__ import annotations

from types import ModuleType
from unittest.mock import patch

from macaw.engines import is_engine_available


class TestIsEngineAvailable:
    def test_known_engine_available(self) -> None:
        """Known engine whose package is installed returns True."""
        fake_spec = ModuleType("fake_spec")
        with patch("macaw.engines.importlib.util.find_spec", return_value=fake_spec):
            assert is_engine_available("faster-whisper") is True

    def test_known_engine_not_available(self) -> None:
        """Known engine whose package is missing returns False."""
        with patch("macaw.engines.importlib.util.find_spec", return_value=None):
            assert is_engine_available("kokoro") is False

    def test_unknown_engine_returns_true(self) -> None:
        """Engine not in ENGINE_PACKAGE mapping returns True (pass-through)."""
        assert is_engine_available("some-future-engine") is True
