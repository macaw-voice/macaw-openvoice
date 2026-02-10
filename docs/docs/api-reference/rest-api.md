---
title: REST API
---

Macaw implements the OpenAI Audio API contract.

## Endpoints

- `POST /v1/audio/transcriptions`
- `POST /v1/audio/translations`
- `POST /v1/audio/speech`

## Transcriptions

```bash
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -F file=@audio.wav \
  -F model=faster-whisper-large-v3
```

## Speech

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro-v1","input":"Hello","voice":"default"}' \
  --output speech.wav
```

For detailed request fields and formats, see `docs/PRD.md`.
