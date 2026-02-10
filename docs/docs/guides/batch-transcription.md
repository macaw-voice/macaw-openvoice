---
title: Batch Transcription
---

Macaw exposes OpenAI-compatible endpoints for batch transcription and translation.

## Transcription

```bash
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -F file=@audio.wav \
  -F model=faster-whisper-large-v3 \
  -F response_format=verbose_json
```

## Translation

```bash
curl -X POST http://localhost:8000/v1/audio/translations \
  -F file=@audio.wav \
  -F model=faster-whisper-large-v3
```

See full request and response formats in [REST API](../api-reference/rest-api).
