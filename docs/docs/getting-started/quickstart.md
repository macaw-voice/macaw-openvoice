---
title: Quickstart
---

Start the runtime and run your first transcription in minutes.

```bash
Macaw serve
```

Send a transcription request:

```bash
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -F file=@audio.wav \
  -F model=faster-whisper-large-v3
```

For WebSocket streaming, see the [Streaming STT guide](../guides/streaming-stt).
