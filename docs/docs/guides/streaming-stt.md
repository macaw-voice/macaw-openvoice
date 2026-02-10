---
title: Streaming STT
---

The `/v1/realtime` endpoint supports low-latency streaming speech-to-text.

## Connect

```bash
wscat -c "ws://localhost:8000/v1/realtime?model=faster-whisper-large-v3"
```

## Send audio

Send binary PCM frames (16-bit). The server returns JSON events for partial and final transcripts.

For the full protocol, see [WebSocket Protocol](../api-reference/websocket-protocol).
