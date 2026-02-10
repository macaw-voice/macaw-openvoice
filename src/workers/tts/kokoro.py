"""Backend TTS para Kokoro.

Implementa TTSBackend usando Kokoro como biblioteca de inferencia.
Kokoro e uma dependencia opcional -- o import e guardado.

Kokoro v0.9.4 API:
  model = kokoro.KModel(config='config.json', model='weights.pth')
  pipeline = kokoro.KPipeline(lang_code='a', model=model, device='cpu')
  for gs, ps, audio in pipeline(text, voice='path/voice.pt', speed=1.0):
      # audio is numpy float32 at 24kHz
"""

from __future__ import annotations

import asyncio
import os
import warnings
from typing import TYPE_CHECKING

import numpy as np

from Macaw._types import VoiceInfo
from Macaw.exceptions import ModelLoadError, TTSSynthesisError
from Macaw.logging import get_logger
from Macaw.workers.tts.interface import TTSBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

try:
    import kokoro as kokoro_lib
except ImportError:
    kokoro_lib = None

logger = get_logger("worker.tts.kokoro")

_DEFAULT_SAMPLE_RATE = 24000

# Tamanho dos chunks de audio retornados pelo synthesize (bytes).
# 4096 bytes = 2048 samples PCM 16-bit = ~85ms a 24kHz.
_CHUNK_SIZE_BYTES = 4096

# Mapeamento de prefixo de voz -> (lang_code, language_name)
_VOICE_LANG_MAP: dict[str, tuple[str, str]] = {
    "a": ("a", "en"),  # American English
    "b": ("b", "en"),  # British English
    "e": ("e", "es"),  # Spanish
    "f": ("f", "fr"),  # French
    "h": ("h", "hi"),  # Hindi
    "i": ("i", "it"),  # Italian
    "j": ("j", "ja"),  # Japanese
    "p": ("p", "pt"),  # Portuguese
    "z": ("z", "zh"),  # Chinese
}


class KokoroBackend(TTSBackend):
    """Backend TTS usando Kokoro v0.9.4 (KModel + KPipeline).

    Sintetiza texto em audio PCM 16-bit via Kokoro. A inferencia
    e executada em executor para nao bloquear o event loop.
    """

    def __init__(self) -> None:
        self._model: object | None = None
        self._pipeline: object | None = None
        self._model_path: str = ""
        self._voices_dir: str = ""
        self._default_voice: str = "af_heart"

    async def load(self, model_path: str, config: dict[str, object]) -> None:
        if kokoro_lib is None:
            msg = "kokoro nao esta instalado. Instale com: pip install Macaw-openvoice[kokoro]"
            raise ModelLoadError(model_path, msg)

        device_str = str(config.get("device", "cpu"))
        device = _resolve_device(device_str)
        lang_code = str(config.get("lang_code", "a"))
        self._default_voice = str(config.get("default_voice", "af_heart"))

        # Find config.json and weights file in model_path
        config_path = os.path.join(model_path, "config.json")
        weights_path = _find_weights_file(model_path)

        if not os.path.isfile(config_path):
            msg = f"config.json nao encontrado em {model_path}"
            raise ModelLoadError(model_path, msg)
        if weights_path is None:
            msg = f"Arquivo .pth nao encontrado em {model_path}"
            raise ModelLoadError(model_path, msg)

        voices_dir = os.path.join(model_path, "voices")
        if os.path.isdir(voices_dir):
            self._voices_dir = voices_dir

        loop = asyncio.get_running_loop()
        try:
            model, pipeline = await loop.run_in_executor(
                None,
                lambda: _load_kokoro_model(
                    config_path,
                    weights_path,
                    lang_code,
                    device,
                ),
            )
        except Exception as exc:
            msg = str(exc)
            raise ModelLoadError(model_path, msg) from exc

        self._model = model
        self._pipeline = pipeline
        self._model_path = model_path
        logger.info(
            "model_loaded",
            model_path=model_path,
            device=device,
            lang_code=lang_code,
            voices_dir=self._voices_dir,
        )

    async def synthesize(  # type: ignore[override, misc]
        self,
        text: str,
        voice: str = "default",
        *,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
        speed: float = 1.0,
    ) -> AsyncIterator[bytes]:
        """Sintetiza texto em audio, retornando chunks PCM 16-bit.

        Args:
            text: Texto a ser sintetizado.
            voice: Identificador da voz ou "default".
            sample_rate: Taxa de amostragem de saida (ignorado, kokoro usa 24kHz).
            speed: Velocidade da sintese (0.25-4.0).

        Yields:
            Chunks de audio PCM 16-bit.

        Raises:
            ModelLoadError: Se modelo nao esta carregado.
            TTSSynthesisError: Se a sintese falhar.
        """
        if self._pipeline is None:
            msg = "Modelo nao carregado. Chame load() primeiro."
            raise ModelLoadError("unknown", msg)

        if not text.strip():
            raise TTSSynthesisError(self._model_path, "Texto vazio")

        voice_path = _resolve_voice_path(
            voice,
            self._voices_dir,
            self._default_voice,
        )

        loop = asyncio.get_running_loop()
        try:
            audio_data = await loop.run_in_executor(
                None,
                lambda: _synthesize_with_pipeline(
                    self._pipeline,
                    text,
                    voice_path,
                    speed,
                ),
            )
        except TTSSynthesisError:
            raise
        except Exception as exc:
            raise TTSSynthesisError(self._model_path, str(exc)) from exc

        if len(audio_data) == 0:
            msg = "Sintese retornou audio vazio"
            raise TTSSynthesisError(self._model_path, msg)

        # Yield em chunks para streaming
        for i in range(0, len(audio_data), _CHUNK_SIZE_BYTES):
            yield audio_data[i : i + _CHUNK_SIZE_BYTES]

    async def voices(self) -> list[VoiceInfo]:
        if not self._voices_dir or not os.path.isdir(self._voices_dir):
            return [
                VoiceInfo(
                    voice_id=self._default_voice,
                    name=self._default_voice,
                    language="en",
                ),
            ]
        return _scan_voices_dir(self._voices_dir)

    async def unload(self) -> None:
        self._model = None
        self._pipeline = None
        self._model_path = ""
        self._voices_dir = ""
        logger.info("model_unloaded")

    async def health(self) -> dict[str, str]:
        if self._model is not None:
            return {"status": "ok"}
        return {"status": "not_loaded"}


# --- Pure helper functions ---


def _resolve_device(device_str: str) -> str:
    """Resolve device string para formato Kokoro.

    Args:
        device_str: "auto", "cpu", "cuda", or "cuda:0".

    Returns:
        Device string no formato esperado pelo Kokoro.
    """
    if device_str == "auto":
        return "cpu"
    return device_str


def _find_weights_file(model_path: str) -> str | None:
    """Encontra o arquivo .pth de pesos no diretorio do modelo.

    Args:
        model_path: Caminho para o diretorio do modelo.

    Returns:
        Caminho completo do arquivo .pth, ou None se nao encontrado.
    """
    if not os.path.isdir(model_path):
        return None
    for name in os.listdir(model_path):
        if name.endswith(".pth"):
            return os.path.join(model_path, name)
    return None


def _load_kokoro_model(
    config_path: str,
    weights_path: str,
    lang_code: str,
    device: str,
) -> tuple[object, object]:
    """Carrega modelo Kokoro e cria pipeline (blocking).

    Args:
        config_path: Caminho para config.json.
        weights_path: Caminho para arquivo .pth.
        lang_code: Codigo de idioma ('a'=en, 'p'=pt, etc).
        device: Device string ("cpu", "cuda").

    Returns:
        Tupla (model, pipeline).
    """
    # Kokoro/PyTorch/spaCy emitem warnings inofensivos durante carregamento:
    # - UserWarning sobre dropout em LSTM com num_layers=1
    # - FutureWarning sobre weight_norm deprecado
    # - DeprecationWarning sobre torch.jit.script deprecado (via spaCy/thinc)
    # Suprimir para evitar que pytest (filterwarnings=error) trate como excecao.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        warnings.filterwarnings("ignore", category=FutureWarning)
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        model = kokoro_lib.KModel(config=config_path, model=weights_path)
        model = model.to(device).eval()
        pipeline = kokoro_lib.KPipeline(
            lang_code=lang_code,
            repo_id="hexgrad/Kokoro-82M",
            model=model,
            device=device,
        )
    return model, pipeline


def _resolve_voice_path(
    voice: str,
    voices_dir: str,
    default_voice: str,
) -> str:
    """Resolve voice name para caminho completo do arquivo .pt.

    Estrategia:
    1. "default" -> default_voice name -> voices_dir/<default_voice>.pt
    2. Nome simples (ex: "af_heart") -> voices_dir/<voice>.pt
    3. Caminho absoluto ou com extensao -> retorna direto

    Args:
        voice: Nome da voz, "default", ou caminho completo.
        voices_dir: Diretorio de vozes do modelo.
        default_voice: Nome da voz padrao (ex: "af_heart").

    Returns:
        Caminho para o arquivo .pt da voz, ou o nome se nao ha voices_dir.
    """
    if voice == "default":
        voice = default_voice

    # Se ja e caminho absoluto ou tem extensao .pt, retorna direto
    if os.path.isabs(voice) or voice.endswith(".pt"):
        return voice

    # Se temos voices_dir, compoe caminho completo
    if voices_dir:
        candidate = os.path.join(voices_dir, f"{voice}.pt")
        if os.path.isfile(candidate):
            return candidate

    # Fallback: retorna o nome (KPipeline resolve internamente)
    return voice


def _synthesize_with_pipeline(
    pipeline: object,
    text: str,
    voice_path: str,
    speed: float,
) -> bytes:
    """Sintetiza texto usando KPipeline do Kokoro (blocking).

    KPipeline retorna um generator de tuplas (graphemes, phonemes, audio).
    Concatenamos todos os arrays de audio e convertemos para PCM 16-bit.

    Args:
        pipeline: KPipeline instance.
        text: Texto a sintetizar.
        voice_path: Caminho para arquivo .pt da voz.
        speed: Velocidade da sintese.

    Returns:
        Audio PCM 16-bit como bytes.

    Raises:
        TTSSynthesisError: Se nenhum audio for produzido.
    """
    audio_arrays: list[np.ndarray] = []

    for _gs, _ps, audio in pipeline(text, voice=voice_path, speed=speed):  # type: ignore[operator]
        if audio is not None and len(audio) > 0:
            # Kokoro v0.9.4 retorna torch.Tensor, converter para numpy
            arr = audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio)
            audio_arrays.append(arr)

    if not audio_arrays:
        msg = "Sintese retornou audio vazio"
        raise TTSSynthesisError("kokoro", msg)

    combined = np.concatenate(audio_arrays)
    return _float32_to_pcm16_bytes(combined)


def _scan_voices_dir(voices_dir: str) -> list[VoiceInfo]:
    """Lista vozes disponiveis escaneando o diretorio voices/.

    Cada arquivo .pt e uma voz. O nome do arquivo (sem extensao)
    e o voice_id. O prefixo determina idioma e genero.

    Args:
        voices_dir: Caminho para o diretorio voices/.

    Returns:
        Lista de VoiceInfo ordenada por voice_id.
    """
    voices: list[VoiceInfo] = []
    for name in sorted(os.listdir(voices_dir)):
        if not name.endswith(".pt"):
            continue
        voice_id = name[:-3]  # remove .pt
        language = _voice_id_to_language(voice_id)
        gender = _voice_id_to_gender(voice_id)
        voices.append(
            VoiceInfo(
                voice_id=voice_id,
                name=voice_id,
                language=language,
                gender=gender,
            ),
        )
    return voices


def _voice_id_to_language(voice_id: str) -> str:
    """Extrai idioma do prefixo do voice_id.

    Convencao kokoro: primeiro char = idioma.
    a=en, b=en, e=es, f=fr, h=hi, i=it, j=ja, p=pt, z=zh.
    """
    if voice_id:
        lang_info = _VOICE_LANG_MAP.get(voice_id[0])
        if lang_info:
            return lang_info[1]
    return "en"


def _voice_id_to_gender(voice_id: str) -> str | None:
    """Extrai genero do prefixo do voice_id.

    Convencao kokoro: segundo char = genero (f=female, m=male).
    """
    if len(voice_id) >= 2:
        if voice_id[1] == "f":
            return "female"
        if voice_id[1] == "m":
            return "male"
    return None


def _float32_to_pcm16_bytes(audio_array: np.ndarray) -> bytes:
    """Converte array float32 normalizado [-1, 1] para bytes PCM 16-bit.

    Args:
        audio_array: Audio float32 normalizado.

    Returns:
        Bytes PCM 16-bit little-endian.
    """
    int16_data = (audio_array * 32768.0).clip(-32768, 32767).astype(np.int16)
    return int16_data.tobytes()
