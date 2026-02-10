---
title: gRPC (Internal)
---

Macaw uses gRPC for runtime-to-worker communication. This API is internal and not meant for direct client use.

Proto files:

- `src/Macaw/proto/stt_worker.proto`
- `src/Macaw/proto/tts_worker.proto`

See `docs/ARCHITECTURE.md` for worker lifecycle details.
