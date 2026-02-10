---
title: WebSocket Protocol
---

The `/v1/realtime` endpoint supports JSON commands and binary audio frames.

## Client to server

- Binary frames: PCM 16-bit audio
- `session.configure`: VAD, language, hot words, TTS model
- `tts.speak`: start TTS synthesis
- `tts.cancel`: cancel active TTS

## Server to client

- `session.created`
- `vad.speech_start`
- `transcript.partial`
- `transcript.final`
- `vad.speech_end`
- `tts.speaking_start`
- `tts.speaking_end`
- `error`

See the full event schema in `docs/PRD.md`.
