---
title: Overview
---

Macaw OpenVoice is organized around a single runtime with isolated gRPC workers per engine.

```
Clients -> API Server -> Scheduler -> gRPC Workers
           |                  |
           |                  +-> TTS (Kokoro)
           +-> STT (Faster-Whisper, WeNet)
```

Core layers:

- API server: OpenAI-compatible REST and WebSocket endpoints
- Scheduler: priority queue, cancellation, batching, latency tracking
- Session manager: ring buffer, WAL, recovery, backpressure
- Pipeline: preprocessing, VAD, post-processing

See `docs/ARCHITECTURE.md` for full details.
