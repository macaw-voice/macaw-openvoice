#!/bin/sh
# This script installs Macaw OpenVoice on Linux and macOS.
# It uses uv (Astral) to install Python 3.12 and the Macaw-openvoice package.
#
# Quick install:
#   curl -fsSL https://raw.githubusercontent.com/useMacaw/Macaw-openvoice/main/install.sh | sh
#
# Environment variables:
#   Macaw_VERSION       Pin to a specific version (default: latest)
#   Macaw_INSTALL_DIR   Custom install directory (default: /opt/Macaw)
#   Macaw_EXTRAS        Pip extras to install (default: server,grpc)
#   Macaw_NO_SERVICE    Skip systemd service setup (set to any value)

set -eu

red="$( (/usr/bin/tput bold || :; /usr/bin/tput setaf 1 || :) 2>&-)"
green="$( (/usr/bin/tput bold || :; /usr/bin/tput setaf 2 || :) 2>&-)"
plain="$( (/usr/bin/tput sgr0 || :) 2>&-)"

status() { echo ">>> $*" >&2; }
error() { echo "${red}ERROR:${plain} $*"; exit 1; }
warning() { echo "${red}WARNING:${plain} $*"; }
success() { echo "${green}$*${plain}"; }

TEMP_DIR=$(mktemp -d)
cleanup() { rm -rf "$TEMP_DIR"; }
trap cleanup EXIT

available() { command -v "$1" >/dev/null; }

OS="$(uname -s)"
ARCH=$(uname -m)
case "$ARCH" in
    x86_64) ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) error "Unsupported architecture: $ARCH" ;;
esac

# Configuration
Macaw_INSTALL_DIR="${Macaw_INSTALL_DIR:-/opt/Macaw}"
Macaw_EXTRAS="${Macaw_EXTRAS:-server,grpc}"
Macaw_VERSION="${Macaw_VERSION:-}"
PYTHON_VERSION="3.12"

###########################################
# macOS
###########################################

if [ "$OS" = "Darwin" ]; then
    if ! available curl; then
        error "curl is required but not found. Please install it first."
    fi

    status "Installing Macaw OpenVoice on macOS..."

    # Install uv if not present
    if ! available uv; then
        status "Installing uv (Python package manager)..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # Source the env to get uv in PATH
        if [ -f "$HOME/.local/bin/env" ]; then
            . "$HOME/.local/bin/env"
        elif [ -f "$HOME/.cargo/env" ]; then
            . "$HOME/.cargo/env"
        fi
        export PATH="$HOME/.local/bin:$PATH"
    fi

    if ! available uv; then
        error "Failed to install uv. Please install it manually: https://docs.astral.sh/uv/getting-started/installation/"
    fi

    status "uv version: $(uv --version)"

    # Create install directory
    Macaw_INSTALL_DIR="${Macaw_INSTALL_DIR:-$HOME/.Macaw}"
    mkdir -p "$Macaw_INSTALL_DIR"

    # Create venv with Python 3.12
    status "Creating Python $PYTHON_VERSION environment in $Macaw_INSTALL_DIR..."
    uv venv --python "$PYTHON_VERSION" "$Macaw_INSTALL_DIR/.venv"

    # Install Macaw-openvoice
    Macaw_PKG="Macaw-openvoice[$Macaw_EXTRAS]"
    if [ -n "$Macaw_VERSION" ]; then
        Macaw_PKG="Macaw-openvoice[$Macaw_EXTRAS]==$Macaw_VERSION"
    fi
    status "Installing $Macaw_PKG..."
    uv pip install --python "$Macaw_INSTALL_DIR/.venv/bin/python" "$Macaw_PKG"

    # Symlink to /usr/local/bin
    status "Adding 'Macaw' command to PATH..."
    mkdir -p "/usr/local/bin" 2>/dev/null || sudo mkdir -p "/usr/local/bin"
    ln -sf "$Macaw_INSTALL_DIR/.venv/bin/Macaw" "/usr/local/bin/Macaw" 2>/dev/null || \
        sudo ln -sf "$Macaw_INSTALL_DIR/.venv/bin/Macaw" "/usr/local/bin/Macaw"

    # GPU detection
    if system_profiler SPDisplaysDataType 2>/dev/null | grep -qi "nvidia\|cuda"; then
        status "NVIDIA GPU detected. To install GPU acceleration:"
        echo "  uv pip install --python $Macaw_INSTALL_DIR/.venv/bin/python 'Macaw-openvoice[faster-whisper]'"
    fi

    success "Install complete. Run 'Macaw serve' to start the API server."
    echo "  API will be available at http://127.0.0.1:8000"
    echo ""
    echo "  Quick start:"
    echo "    Macaw serve &"
    echo "    Macaw pull faster-whisper-large-v3"
    echo "    Macaw transcribe audio.wav"
    exit 0
fi

###########################################
# Linux
###########################################

[ "$OS" = "Linux" ] || error 'This script is intended to run on Linux and macOS only.'

IS_WSL2=false
KERN=$(uname -r)
case "$KERN" in
    *icrosoft*WSL2 | *icrosoft*wsl2) IS_WSL2=true ;;
    *icrosoft) error "Microsoft WSL1 is not currently supported. Please use WSL2 with 'wsl --set-version <distro> 2'" ;;
    *) ;;
esac

SUDO=
if [ "$(id -u)" -ne 0 ]; then
    if ! available sudo; then
        error "This script requires superuser permissions. Please re-run as root."
    fi
    SUDO="sudo"
fi

if ! available curl; then
    error "curl is required but not found. Please install it first."
fi

status "Installing Macaw OpenVoice on Linux ($ARCH)..."

# Install uv if not present
if ! available uv; then
    status "Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Source the env to get uv in PATH
    if [ -f "$HOME/.local/bin/env" ]; then
        . "$HOME/.local/bin/env"
    elif [ -f "$HOME/.cargo/env" ]; then
        . "$HOME/.cargo/env"
    fi
    export PATH="$HOME/.local/bin:$PATH"
fi

if ! available uv; then
    error "Failed to install uv. Please install it manually: https://docs.astral.sh/uv/getting-started/installation/"
fi

status "uv version: $(uv --version)"

# Create install directory
status "Creating install directory at $Macaw_INSTALL_DIR..."
$SUDO mkdir -p "$Macaw_INSTALL_DIR"
$SUDO chown "$(id -u):$(id -g)" "$Macaw_INSTALL_DIR"

# Create venv with Python 3.12
status "Creating Python $PYTHON_VERSION environment..."
uv venv --python "$PYTHON_VERSION" "$Macaw_INSTALL_DIR/.venv"

# Install Macaw-openvoice
Macaw_PKG="Macaw-openvoice[$Macaw_EXTRAS]"
if [ -n "$Macaw_VERSION" ]; then
    Macaw_PKG="Macaw-openvoice[$Macaw_EXTRAS]==$Macaw_VERSION"
fi
status "Installing $Macaw_PKG..."
uv pip install --python "$Macaw_INSTALL_DIR/.venv/bin/python" "$Macaw_PKG"

# Symlink to PATH
for BINDIR in /usr/local/bin /usr/bin /bin; do
    echo "$PATH" | grep -q "$BINDIR" && break || continue
done

status "Adding 'Macaw' command to PATH in $BINDIR..."
$SUDO ln -sf "$Macaw_INSTALL_DIR/.venv/bin/Macaw" "$BINDIR/Macaw"

install_success() {
    success "Install complete."
    echo "  The Macaw OpenVoice API is available at http://127.0.0.1:8000"
    echo ""
    echo "  Quick start:"
    echo "    Macaw serve &"
    echo "    Macaw pull faster-whisper-large-v3"
    echo "    Macaw transcribe audio.wav"
}

# Configure systemd service (optional)
configure_systemd() {
    if [ -n "${Macaw_NO_SERVICE:-}" ]; then
        status "Skipping systemd service setup (Macaw_NO_SERVICE is set)."
        return
    fi

    if ! id Macaw >/dev/null 2>&1; then
        status "Creating Macaw user..."
        $SUDO useradd -r -s /bin/false -U -m -d /var/lib/Macaw Macaw
    fi
    if getent group render >/dev/null 2>&1; then
        status "Adding Macaw user to render group..."
        $SUDO usermod -a -G render Macaw
    fi
    if getent group video >/dev/null 2>&1; then
        status "Adding Macaw user to video group..."
        $SUDO usermod -a -G video Macaw
    fi

    status "Adding current user to Macaw group..."
    $SUDO usermod -a -G Macaw "$(whoami)"

    status "Creating Macaw systemd service..."
    cat <<EOF | $SUDO tee /etc/systemd/system/Macaw.service >/dev/null
[Unit]
Description=Macaw OpenVoice Service
After=network-online.target

[Service]
ExecStart=$Macaw_INSTALL_DIR/.venv/bin/Macaw serve --host 0.0.0.0 --port 8000
User=Macaw
Group=Macaw
Restart=always
RestartSec=3
Environment="PATH=$Macaw_INSTALL_DIR/.venv/bin:$PATH"
Environment="Macaw_MODELS_DIR=/var/lib/Macaw/models"
WorkingDirectory=/var/lib/Macaw

[Install]
WantedBy=default.target
EOF

    # Create models directory
    $SUDO mkdir -p /var/lib/Macaw/models
    $SUDO chown -R Macaw:Macaw /var/lib/Macaw

    SYSTEMCTL_RUNNING="$(systemctl is-system-running || true)"
    case $SYSTEMCTL_RUNNING in
        running|degraded)
            status "Enabling and starting Macaw service..."
            $SUDO systemctl daemon-reload
            $SUDO systemctl enable Macaw

            start_service() { $SUDO systemctl restart Macaw; }
            trap start_service EXIT
            ;;
        *)
            warning "systemd is not running."
            if [ "$IS_WSL2" = true ]; then
                warning "See https://learn.microsoft.com/en-us/windows/wsl/systemd#how-to-enable-systemd to enable it."
            fi
            ;;
    esac
}

if available systemctl; then
    configure_systemd
fi

# GPU detection
check_gpu() {
    case $1 in
        lspci)
            case $2 in
                nvidia) available lspci && lspci -d '10de:' | grep -q 'NVIDIA' || return 1 ;;
            esac ;;
        lshw)
            case $2 in
                nvidia) available lshw && $SUDO lshw -c display -numeric -disable network | grep -q 'vendor: .* \[10DE\]' || return 1 ;;
            esac ;;
        nvidia-smi) available nvidia-smi || return 1 ;;
    esac
}

if check_gpu nvidia-smi; then
    status "NVIDIA GPU detected with drivers installed."
    status "Installing GPU-accelerated STT engine..."
    uv pip install --python "$Macaw_INSTALL_DIR/.venv/bin/python" "Macaw-openvoice[faster-whisper]" || \
        warning "Failed to install faster-whisper GPU extras. You can install manually later."
elif (check_gpu lspci nvidia 2>/dev/null || check_gpu lshw nvidia 2>/dev/null); then
    warning "NVIDIA GPU detected but nvidia-smi not found. Install NVIDIA drivers first."
    echo "  After installing drivers, run:"
    echo "    uv pip install --python $Macaw_INSTALL_DIR/.venv/bin/python 'Macaw-openvoice[faster-whisper]'"
elif [ "$IS_WSL2" = true ] && available nvidia-smi; then
    status "NVIDIA GPU detected via WSL2 passthrough."
    status "Installing GPU-accelerated STT engine..."
    uv pip install --python "$Macaw_INSTALL_DIR/.venv/bin/python" "Macaw-openvoice[faster-whisper]" || \
        warning "Failed to install faster-whisper GPU extras. You can install manually later."
else
    status "No NVIDIA GPU detected. Macaw will run in CPU-only mode."
    echo "  CPU-only mode is fully functional but slower for large models."
fi

install_success
