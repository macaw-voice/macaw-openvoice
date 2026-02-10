#!/usr/bin/env bash
set -euo pipefail

PYTHON=".venv/bin/python"

if [ ! -f "$PYTHON" ]; then
    echo "Venv nao encontrado. Execute ./setup.sh primeiro."
    exit 1
fi

HOST=${HOST:-127.0.0.1}
PORT=${PORT:-9000}
UVICORN_RELOAD_DEFAULT=1
UVICORN_ENABLE_RELOAD=${UVICORN_RELOAD:-$UVICORN_RELOAD_DEFAULT}

echo "Macaw OpenVoice v$($PYTHON -c 'import Macaw; print(Macaw.__version__)')"
echo "Iniciando demo backend em http://$HOST:$PORT"

UVICORN_ARGS=()
if [ "$UVICORN_ENABLE_RELOAD" != "0" ]; then
    UVICORN_ARGS+=(--reload)
fi
UVICORN_ARGS+=(--host "$HOST" --port "$PORT")

exec "$PYTHON" -m uvicorn examples.demo.backend.app:app "${UVICORN_ARGS[@]}" "$@"
