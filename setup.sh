#!/usr/bin/env bash
set -euo pipefail

VENV=".venv"

echo "=== Macaw OpenVoice Setup ==="

if [ ! -d "$VENV" ]; then
    echo "Criando venv com Python 3.12..."
    uv venv --python 3.12 "$VENV"
fi

echo "Instalando dependencias..."
uv pip install -e ".[dev]"

echo ""
echo "Setup completo. Use:"
echo "  ./run.sh   — executar o servidor"
echo "  ./test.sh  — rodar lint, typecheck e testes"
