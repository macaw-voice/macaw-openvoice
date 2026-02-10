#!/usr/bin/env bash
set -euo pipefail

VENV=".venv"
PYTHON="$VENV/bin/python"

# ── Verificacao de venv ──────────────────────────────────────────
if [ ! -f "$PYTHON" ]; then
    echo "Venv nao encontrado em $VENV/"
    echo "Execute primeiro:  ./setup.sh"
    exit 1
fi

# Detecta se usa uv ou pip (venv criado com uv nao inclui pip)
if command -v uv &>/dev/null; then
    PIP="uv pip"
elif "$PYTHON" -m pip --version &>/dev/null; then
    PIP="$PYTHON -m pip"
else
    echo "Nem uv nem pip encontrados. Instale uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

PY_VERSION=$("$PYTHON" --version 2>&1)

usage() {
    echo "Macaw OpenVoice — Dev Helper ($PY_VERSION)"
    echo ""
    echo "Uso: ./dev.sh <comando> [args...]"
    echo ""
    echo "Comandos:"
    echo "  install [extras]    Instala o projeto em modo editavel"
    echo "                      ./dev.sh install          → pip install -e ."
    echo "                      ./dev.sh install all      → pip install -e '.[all]'"
    echo "                      ./dev.sh install dev,grpc → pip install -e '.[dev,grpc]'"
    echo "  pip <args>          Executa pip (via uv) no venv"
    echo "                      ./dev.sh pip list"
    echo "                      ./dev.sh pip install numpy"
    echo "  test [args]         Roda pytest (unit tests)"
    echo "                      ./dev.sh test"
    echo "                      ./dev.sh test tests/unit/test_types.py -v"
    echo "  lint                Roda ruff check + format check"
    echo "  format              Formata codigo com ruff"
    echo "  typecheck           Roda mypy"
    echo "  check               Roda lint + typecheck + test (CI completo)"
    echo "  proto               Gera stubs protobuf"
    echo "  python <args>       Executa python do venv"
    echo "                      ./dev.sh python -c 'import Macaw; print(Macaw.__version__)'"
    echo "  shell               Abre shell com venv ativado"
    echo "  info                Mostra informacoes do ambiente"
    echo ""
}

cmd_install() {
    local extras="${1:-}"
    if [ -z "$extras" ]; then
        echo "==> $PIP install -e ."
        $PIP install -e . --python "$PYTHON"
    else
        echo "==> $PIP install -e '.[$extras]'"
        $PIP install -e ".[$extras]" --python "$PYTHON"
    fi
}

cmd_pip() {
    $PIP "$@" --python "$PYTHON"
}

cmd_test() {
    if [ $# -eq 0 ]; then
        "$PYTHON" -m pytest tests/unit/ -v
    else
        "$PYTHON" -m pytest "$@"
    fi
}

cmd_lint() {
    echo "=== Ruff Check ==="
    "$PYTHON" -m ruff check src/ tests/
    echo "=== Ruff Format Check ==="
    "$PYTHON" -m ruff format --check src/ tests/
}

cmd_format() {
    "$PYTHON" -m ruff format src/ tests/
    "$PYTHON" -m ruff check --fix src/ tests/
}

cmd_typecheck() {
    "$PYTHON" -m mypy src/
}

cmd_check() {
    cmd_lint
    echo ""
    cmd_typecheck
    echo ""
    cmd_test "$@"
}

cmd_proto() {
    if [ -f "scripts/generate_proto.sh" ]; then
        bash scripts/generate_proto.sh
    else
        echo "Script scripts/generate_proto.sh nao encontrado."
        exit 1
    fi
}

cmd_python() {
    "$PYTHON" "$@"
}

cmd_shell() {
    echo "Ativando venv ($PY_VERSION)..."
    echo "Use 'exit' para sair."
    # shellcheck disable=SC1091
    exec bash --init-file <(echo "source $VENV/bin/activate && echo 'Venv ativado: $PY_VERSION'")
}

cmd_info() {
    echo "Macaw OpenVoice — Ambiente de Desenvolvimento"
    echo ""
    echo "Python:    $("$PYTHON" --version 2>&1)"
    echo "Path:      $(realpath "$PYTHON")"
    echo "Installer: $PIP"
    echo "Venv:      $(realpath "$VENV")"
    echo "Project:   $(pwd)"
    echo ""
    echo "Pacotes instalados (Macaw*):"
    $PIP list --python "$PYTHON" 2>/dev/null | grep -i Macaw || echo "  (nenhum)"
}

# ── Dispatch ─────────────────────────────────────────────────────
if [ $# -eq 0 ]; then
    usage
    exit 0
fi

COMMAND="$1"
shift

case "$COMMAND" in
    install)    cmd_install "$@" ;;
    pip)        cmd_pip "$@" ;;
    test)       cmd_test "$@" ;;
    lint)       cmd_lint ;;
    format)     cmd_format ;;
    typecheck)  cmd_typecheck ;;
    check)      cmd_check "$@" ;;
    proto)      cmd_proto ;;
    python)     cmd_python "$@" ;;
    shell)      cmd_shell ;;
    info)       cmd_info ;;
    help|-h|--help) usage ;;
    *)
        echo "Comando desconhecido: $COMMAND"
        echo ""
        usage
        exit 1
        ;;
esac
