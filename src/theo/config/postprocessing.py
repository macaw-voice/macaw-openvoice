"""Configuracao do Post-Processing Pipeline."""

from __future__ import annotations

from pydantic import BaseModel


class ITNConfig(BaseModel):
    """Configuracao de Inverse Text Normalization."""

    enabled: bool = True
    language: str = "pt"


class EntityFormattingConfig(BaseModel):
    """Configuracao de formatacao de entidades."""

    enabled: bool = False
    domain: str = "generic"


class HotWordCorrectionConfig(BaseModel):
    """Configuracao de correcao de hot words."""

    enabled: bool = False
    max_edit_distance: int = 2


class PostProcessingConfig(BaseModel):
    """Configuracao do pipeline de pos-processamento de texto."""

    itn: ITNConfig = ITNConfig()
    entity_formatting: EntityFormattingConfig = EntityFormattingConfig()
    hot_word_correction: HotWordCorrectionConfig = HotWordCorrectionConfig()
