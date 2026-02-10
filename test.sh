#!/usr/bin/env bash
set -euo pipefail

PYTHON=".venv/bin/python"

if [ ! -f "$PYTHON" ]; then
    echo "Venv nao encontrado. Execute ./setup.sh primeiro."
    exit 1
fi

echo "=== Ruff Check ==="
$PYTHON -m ruff check src/ tests/

echo "=== Ruff Format ==="
$PYTHON -m ruff format --check src/ tests/

echo "=== Mypy ==="
$PYTHON -m mypy src/

echo "=== Pytest ==="
$PYTHON -m pytest tests/unit/ -v "$@"
