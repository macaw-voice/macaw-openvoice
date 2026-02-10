"""Parsing e validacao de manifestos Macaw.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

from Macaw._types import ModelType, STTArchitecture  # noqa: TC001 - Pydantic needs at runtime
from Macaw.exceptions import ManifestParseError, ManifestValidationError


class ModelCapabilities(BaseModel):
    """Capabilities declaradas no manifesto."""

    streaming: bool = False
    architecture: STTArchitecture | None = None
    languages: list[str] = []
    word_timestamps: bool = False
    translation: bool = False
    partial_transcripts: bool = False
    hot_words: bool = False
    batch_inference: bool = False
    language_detection: bool = False
    initial_prompt: bool = False


class ModelResources(BaseModel):
    """Recursos necessarios para o modelo."""

    memory_mb: int
    gpu_required: bool = False
    gpu_recommended: bool = False
    load_time_seconds: int = 10


class EngineConfig(BaseModel, extra="allow"):
    """Configuracao especifica da engine.

    Aceita campos extras porque cada engine tem parametros proprios.
    """

    model_size: str | None = None
    compute_type: str = "float16"
    device: str = "auto"
    beam_size: int = 5
    vad_filter: bool = False


class ModelManifest(BaseModel):
    """Manifesto de modelo Macaw (Macaw.yaml).

    Descreve capabilities, recursos e configuracao de um modelo
    instalado no registry local.
    """

    name: str
    version: str
    engine: str
    model_type: ModelType
    description: str = ""
    capabilities: ModelCapabilities = ModelCapabilities()
    resources: ModelResources
    engine_config: EngineConfig = EngineConfig()

    @field_validator("name")
    @classmethod
    def name_must_be_valid(cls, v: str) -> str:
        if not v or not v.replace("-", "").replace("_", "").isalnum():
            msg = (
                f"Nome de modelo invalido: '{v}'. Use apenas alfanumericos, hifens e underscores."
            )
            raise ValueError(msg)
        return v

    @classmethod
    def from_yaml_path(cls, path: str | Path) -> ModelManifest:
        """Carrega manifesto a partir de arquivo YAML."""
        path = Path(path)
        if not path.exists():
            raise ManifestParseError(str(path), "Arquivo nao encontrado")

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ManifestParseError(str(path), f"Erro ao ler arquivo: {e}") from e

        return cls.from_yaml_string(raw, source_path=str(path))

    @classmethod
    def from_yaml_string(cls, raw: str, source_path: str = "<string>") -> ModelManifest:
        """Carrega manifesto a partir de string YAML."""
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            raise ManifestParseError(source_path, f"YAML invalido: {e}") from e

        if not isinstance(data, dict):
            raise ManifestParseError(source_path, "Conteudo YAML deve ser um mapeamento")

        # Normalizar campo 'type' -> 'model_type' (Macaw.yaml usa 'type')
        if "type" in data and "model_type" not in data:
            data["model_type"] = data.pop("type")

        try:
            return cls.model_validate(data)
        except Exception as e:
            errors = [str(e)]
            raise ManifestValidationError(source_path, errors) from e
