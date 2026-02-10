# Macaw OpenVoice Demo

Aplicacao de demonstracao end-to-end com backend FastAPI e frontend React/Next.js (componentes shadcn/Radix UI).

## Inicio Rapido

```bash
./examples/demo/start-demo.sh
```

Isso inicia backend (porta 9000) e frontend (porta 3000) juntos. Ctrl+C encerra ambos.

## Estrutura

```
examples/demo/
  backend/          # FastAPI: registry, workers gRPC, scheduler, rotas Macaw + /demo/*
  frontend/         # Next.js 14: dashboard, streaming STT, TTS playback
  start-demo.sh     # Script que inicia backend + frontend
```

## Pre-requisitos

- Python 3.12+ (via `uv`)
- Node.js 18+
- Pelo menos um modelo STT instalado em `~/.Macaw/models` (ou configure `DEMO_MODELS_DIR`)

## Instalacao

### Backend

```bash
# Do root do projeto
cd /path/to/Macaw-openvoice
.venv/bin/pip install -e ".[server,grpc]"
```

### Frontend

```bash
cd examples/demo/frontend
npm install
```

## Iniciando Separadamente

### So backend

```bash
# Opcao 1: script
SKIP_FRONTEND=1 ./examples/demo/start-demo.sh

# Opcao 2: direto
.venv/bin/python -m uvicorn examples.demo.backend.app:app --reload --host 127.0.0.1 --port 9000
```

### So frontend

```bash
# Opcao 1: script
SKIP_BACKEND=1 ./examples/demo/start-demo.sh

# Opcao 2: direto
cd examples/demo/frontend
NEXT_PUBLIC_DEMO_API=http://localhost:9000 npm run dev
```

## Variaveis de Ambiente

| Variavel | Default | Descricao |
|----------|---------|-----------|
| `DEMO_HOST` | `127.0.0.1` | Host do backend |
| `DEMO_PORT` | `9000` | Porta do backend |
| `FRONTEND_PORT` | `3000` | Porta do frontend Next.js |
| `DEMO_MODELS_DIR` | `~/.Macaw/models` | Diretorio dos modelos |
| `DEMO_ALLOWED_ORIGINS` | `http://localhost:3000` | CORS origins (separados por virgula) |
| `DEMO_BATCH_ACCUMULATE_MS` | `75` | Tempo de acumulacao do batcher |
| `DEMO_BATCH_MAX_SIZE` | `8` | Tamanho maximo do batch |
| `UVICORN_RELOAD` | `1` | Hot-reload do backend (`0` para desabilitar) |
| `SKIP_FRONTEND` | `0` | `1` para iniciar so o backend |
| `SKIP_BACKEND` | `0` | `1` para iniciar so o frontend |
| `NEXT_PUBLIC_DEMO_API` | `http://localhost:9000` | URL do backend para o frontend |

## Funcionalidades da Demo

A interface tem 3 tabs:

### Dashboard (Batch STT)
- Lista de modelos instalados (STT/TTS) com badges de arquitetura
- Metricas da fila do scheduler (profundidade, prioridade)
- Upload de arquivo de audio para transcricao batch
- Tabela de jobs com status, resultado e cancelamento

### Streaming STT
- Gravacao de microfone em tempo real via Web Audio API
- WebSocket `/v1/realtime` com protocolo de eventos JSON
- Indicadores visuais: conexao, VAD (fala detectada), waveform
- Transcricoes parciais e finais com scroll automatico

### Text-to-Speech
- Sintese de voz via `POST /v1/audio/speech`
- Controles: voz, velocidade (0.5x-2.0x)
- Player de audio integrado
- Medicao de TTFB (Time to First Byte)

## Endpoints

### Rotas Macaw (prefixo `/api`)
- `POST /api/v1/audio/transcriptions` — transcricao batch
- `POST /api/v1/audio/translations` — traducao para ingles
- `POST /api/v1/audio/speech` — sintese TTS
- `WS /api/v1/realtime` — streaming STT + TTS full-duplex
- `GET /api/health` — health check

### Rotas Demo
- `GET /demo/models` — lista modelos do registry
- `GET /demo/queue` — metricas da fila
- `GET /demo/jobs` — lista jobs
- `POST /demo/jobs` — submete job de transcricao
- `POST /demo/jobs/{id}/cancel` — cancela job

## Observabilidade

- Swagger UI: http://localhost:9000/docs
- Health: http://localhost:9000/api/health
- Scheduler real com PriorityQueue, CancellationManager, BatchAccumulator e LatencyTracker
- Workers gRPC isolados como subprocessos
