"""Pipeline de pos-processamento de texto (ITN, entity formatting, hot words)."""

from __future__ import annotations

from Macaw.postprocessing.pipeline import PostProcessingPipeline
from Macaw.postprocessing.stages import TextStage

__all__ = ["PostProcessingPipeline", "TextStage"]
