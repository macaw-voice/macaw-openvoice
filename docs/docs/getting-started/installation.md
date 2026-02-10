---
title: Installation
---

Macaw OpenVoice requires Python 3.11+ and uses optional extras to install engines.

## Install with pip

```bash
pip install Macaw-openvoice[server,grpc,faster-whisper]
```

Optional extras:

- `wenet` for WeNet STT
- `kokoro` for Kokoro TTS
- `itn` for NeMo ITN

Example:

```bash
pip install Macaw-openvoice[server,grpc,faster-whisper,wenet,kokoro]
```

## Install with uv

```bash
uv venv --python 3.12
uv sync --all-extras
```

## GPU note

If you plan to run GPU workloads, ensure CUDA drivers are installed and the engine package supports your GPU.
