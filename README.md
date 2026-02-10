<p align="center">
  <h1 align="center">Macaw OpenVoice</h1>
  <p align="center">
    <strong>Unified voice runtime (STT + TTS) with OpenAI-compatible API</strong>
  </p>
  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+"></a>
    <a href="https://github.com/useMacaw/Macaw-openvoice/actions"><img src="https://img.shields.io/github/actions/workflow/status/useMacaw/Macaw-openvoice/ci.yml?branch=main&label=tests" alt="Tests"></a>
    <a href="https://pypi.org/project/Macaw-openvoice/"><img src="https://img.shields.io/pypi/v/Macaw-openvoice" alt="PyPI"></a>
  </p>
</p>

---

Macaw OpenVoice is a **voice runtime built from scratch** in Python. It orchestrates inference engines (Faster-Whisper, WeNet, Silero VAD, Kokoro) within a single binary that serves both STT and TTS through an OpenAI-compatible API and an Ollama-inspired CLI.

Macaw is **not** a fork, wrapper, or extension of existing projects. It is the **runtime layer** that sits between inference engines and production: session management, preprocessing, post-processing, scheduling, observability, and a unified CLI.

## Features

- **OpenAI-compatible API** — `POST /v1/audio/transcriptions`, `/translations`, `/speech`, `WS /v1/realtime`
- **Full-duplex STT + TTS** — simultaneous speech-to-text and text-to-speech on the same WebSocket
- **Real-time streaming** — partial and final transcripts via WebSocket with <300ms TTFB
- **Multi-engine** — Faster-Whisper (encoder-decoder), WeNet (CTC), Kokoro (TTS) with a single interface
- **Session Manager** — 6-state machine, ring buffer, WAL, crash recovery without segment duplication
- **Voice Activity Detection** — Silero VAD + energy pre-filter, sensitivity levels (high/normal/low)
- **Audio preprocessing** — resample, DC remove, gain normalize (any sample rate to 16kHz)
- **Post-processing** — Inverse Text Normalization via NeMo ("dois mil" to "2000")
- **Mute-on-speak** — STT pauses during TTS to prevent feedback loops
- **Hot words** — domain-specific keyword boosting per session
- **CLI** — `Macaw serve`, `Macaw transcribe`, `Macaw translate`, `Macaw list` (Ollama-style UX)
- **Observability** — Prometheus metrics for TTFB, session duration, VAD events, TTS latency

## Quick Start

```bash
# Install
pip install Macaw-openvoice[server,grpc,faster-whisper]

# Start the runtime
Macaw serve

# Transcribe a file
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -F file=@audio.wav \
  -F model=faster-whisper-large-v3

# Or via CLI
Macaw transcribe audio.wav --model faster-whisper-large-v3
```

### Streaming via WebSocket

```bash
wscat -c "ws://localhost:8000/v1/realtime?model=faster-whisper-large-v3"
# Send binary audio frames, receive JSON transcript events
```

### Text-to-Speech

```bash
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model": "kokoro-v1", "input": "Hello, how can I help you?", "voice": "default"}' \
  --output speech.wav
```

## Architecture

```
                         Clients
          CLI / REST / WebSocket (full-duplex)
                           |
                           v
  +----------------------------------------------------+
  |              API Server (FastAPI)                    |
  |                                                    |
  |  POST /v1/audio/transcriptions    (STT batch)      |
  |  POST /v1/audio/translations      (STT translate)  |
  |  POST /v1/audio/speech            (TTS)            |
  |  WS   /v1/realtime                (STT+TTS)        |
  +----------------------------------------------------+
  |              Scheduler                              |
  |  Priority queue (realtime > batch), cancellation,   |
  |  dynamic batching, latency tracking                 |
  +----------------------------------------------------+
  |              Model Registry                         |
  |  Declarative manifest (Macaw.yaml), lifecycle        |
  +----------+-------------------+---------------------+
             |                   |
    +--------+--------+  +------+-------+
    |  STT Workers    |  |  TTS Workers |
    |  (subprocess    |  |  (subprocess |
    |   gRPC)         |  |   gRPC)      |
    |                 |  |              |
    | Faster-Whisper  |  | Kokoro       |
    | WeNet           |  |              |
    +-----------------+  +--------------+
             |
  +----------+-------------------------------------+
  |  Audio Preprocessing Pipeline                   |
  |  Resample -> DC Remove -> Gain Normalize        |
  +------------------------------------------------+
  |  Session Manager (STT only)                     |
  |  6 states, ring buffer, WAL, LocalAgreement,    |
  |  cross-segment context, crash recovery          |
  +------------------------------------------------+
  |  VAD (Energy Pre-filter + Silero VAD)           |
  +------------------------------------------------+
  |  Post-Processing (ITN via NeMo)                 |
  +------------------------------------------------+
```

## Supported Models

| Engine | Type | Architecture | Partials | Hot Words | Status |
|--------|------|-------------|----------|-----------|--------|
| [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) | STT | encoder-decoder | LocalAgreement | via initial_prompt | Supported |
| [WeNet](https://github.com/wenet-e2e/wenet) | STT | CTC | native | native keyword boosting | Supported |
| [Kokoro](https://github.com/hexgrad/kokoro) | TTS | — | — | — | Supported |

Adding a new engine requires ~400-700 lines of code and zero changes to the runtime core. See the [Adding an Engine](https://useMacaw.github.io/Macaw-openvoice/docs/guides/adding-engine) guide.

## API Compatibility

Macaw implements the [OpenAI Audio API](https://platform.openai.com/docs/api-reference/audio) contract, so existing SDKs work without modification:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")

# Transcription
result = client.audio.transcriptions.create(
    model="faster-whisper-large-v3",
    file=open("audio.wav", "rb"),
)
print(result.text)

# Text-to-Speech
response = client.audio.speech.create(
    model="kokoro-v1",
    input="Hello, how can I help you?",
    voice="default",
)
response.stream_to_file("output.wav")
```

## WebSocket Protocol

The `/v1/realtime` endpoint supports full-duplex STT + TTS:

```
Client -> Server:
  Binary frames     PCM 16-bit audio (any sample rate)
  session.configure  Configure VAD, language, hot words, TTS model
  tts.speak          Trigger text-to-speech synthesis
  tts.cancel         Cancel active TTS

Server -> Client:
  session.created     Session established
  vad.speech_start    Speech detected
  transcript.partial  Intermediate hypothesis
  transcript.final    Confirmed segment (with ITN)
  vad.speech_end      Speech ended
  tts.speaking_start  TTS started (STT muted)
  Binary frames       TTS audio output
  tts.speaking_end    TTS finished (STT unmuted)
  error               Error with recoverable flag
```

## CLI

```bash
Macaw serve                                   # Start API server
Macaw transcribe audio.wav                    # Transcribe file
Macaw transcribe audio.wav --format srt       # Generate subtitles
Macaw transcribe --stream                     # Stream from microphone
Macaw translate audio.wav                     # Translate to English
Macaw list                                    # List installed models
Macaw inspect faster-whisper-large-v3         # Model details
```

## Development

```bash
# Setup (requires Python 3.11+ and uv)
uv venv --python 3.12
uv sync --all-extras

# Development workflow
make check       # format + lint + typecheck
make test-unit   # unit tests (preferred during development)
make test        # all tests (1600+)
make ci          # full pipeline: format + lint + typecheck + test
```

## Documentation

Full documentation is available at **[useMacaw.github.io/Macaw-openvoice](https://useMacaw.github.io/Macaw-openvoice)**.

- [Getting Started](https://useMacaw.github.io/Macaw-openvoice/docs/getting-started/installation)
- [Streaming Guide](https://useMacaw.github.io/Macaw-openvoice/docs/guides/streaming-stt)
- [Full-Duplex Guide](https://useMacaw.github.io/Macaw-openvoice/docs/guides/full-duplex)
- [Adding an Engine](https://useMacaw.github.io/Macaw-openvoice/docs/guides/adding-engine)
- [API Reference](https://useMacaw.github.io/Macaw-openvoice/docs/api-reference/rest-api)
- [Architecture](https://useMacaw.github.io/Macaw-openvoice/docs/architecture/overview)

## Contributing

We welcome contributions! Please read our [Contributing Guide](CONTRIBUTING.md) before submitting a pull request.

## License

[Apache License 2.0](LICENSE)
