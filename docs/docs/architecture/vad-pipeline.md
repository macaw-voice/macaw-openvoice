---
title: VAD Pipeline
---

Macaw applies preprocessing before VAD for consistent thresholds across engines.

Pipeline order:

1. Resample to 16 kHz
2. DC removal
3. Gain normalization
4. Energy pre-filter
5. Silero VAD

This keeps VAD behavior stable regardless of the engine.
