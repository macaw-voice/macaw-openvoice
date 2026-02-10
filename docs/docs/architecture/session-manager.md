---
title: Session Manager
---

The Session Manager coordinates streaming STT with a state machine, ring buffer, and WAL-based recovery.

Key concepts:

- Six states (INIT, ACTIVE, SILENCE, HOLD, CLOSING, CLOSED)
- Ring buffer with read fence and force-commit
- WAL checkpoints for crash recovery

See `docs/ARCHITECTURE.md` and `docs/PRD.md` for details.
