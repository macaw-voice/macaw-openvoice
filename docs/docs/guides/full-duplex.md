---
title: Full-Duplex STT + TTS
---

Macaw supports full-duplex interactions on a single WebSocket. When TTS is active, STT is muted to prevent feedback loops.

## Flow

1. Client streams audio frames for STT
2. Client sends `tts.speak` command
3. Server emits `tts.speaking_start` and streams audio bytes
4. Server emits `tts.speaking_end` and STT resumes

See the runtime spec in `docs/FULL_DUPLEX.md` for detailed guidance.
