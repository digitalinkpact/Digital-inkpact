#!/usr/bin/env bash
# =============================================================================
# Autonomous Bid Processing Assistant - Installer (macOS/Linux)
#
# One-click installer that sets up all dependencies:
#   - Go (for nanobot)
#   - Ollama (local LLM)
#   - nanobot (lightweight chat interface with MCP)
#   - Python virtual environment with required packages
#   - AgentGuard security policy
#   - Directory structure and configuration
#
# Usage: bash install.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${SCRIPT_DIR}"
VENV_DIR="${INSTALL_DIR}/venv"
LOG_DIR="${INSTALL_DIR}/logs"
CONFIG_DIR="${INSTALL_DIR}/config"
SECURITY_DIR="${INSTALL_DIR}/security"
OLLAMA_MODEL="mistral:7b"
NANOBOT_VERSION="latest"
MIN_PYTHON="3.9"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

check_command() {
    command -v "$1" &>/dev/null
}

detect_os() {
    case "$(uname -s)" in
        Darwin*)  echo "macos"  ;;
        Linux*)   echo "linux"  ;;
        *)        echo "unknown" ;;
    esac
}

detect_arch() {
    case "$(uname -m)" in
        x86_64)   echo "amd64" ;;
        aarch64)  echo "arm64" ;;
        arm64)    echo "arm64" ;;
        *)        echo "unknown" ;;
    esac
}

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
preflight_checks() {
    log_info "Running preflight checks..."

    OS="$(detect_os)"
    ARCH="$(detect_arch)"

    if [[ "${OS}" == "unknown" ]]; then
        log_error "Unsupported operating system: $(uname -s)"
        exit 1
    fi

    if [[ "${ARCH}" == "unknown" ]]; then
        log_error "Unsupported architecture: $(uname -m)"
        exit 1
    fi

    log_ok "Detected OS=${OS} ARCH=${ARCH}"

    # Check for curl or wget
    if ! check_command curl && ! check_command wget; then
        log_error "curl or wget is required. Install one and retry."
        exit 1
    fi

    # Check disk space (need ~5 GB for models)
    AVAIL_KB=$(df -k "${HOME}" | awk 'NR==2 {print $4}')
    AVAIL_GB=$(( AVAIL_KB / 1024 / 1024 ))
    if (( AVAIL_GB < 5 )); then
        log_warn "Only ${AVAIL_GB} GB free disk space. Models require ~5 GB."
    fi
}

# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------
setup_directories() {
    log_info "Creating directory structure at ${INSTALL_DIR}..."

    mkdir -p "${INSTALL_DIR}"/{agent,config,scripts,security,logs,models,mcp,samples}
    mkdir -p "${HOME}/Documents/Bids"

    log_ok "Directories created."
}

# ---------------------------------------------------------------------------
# Python installation / verification
# ---------------------------------------------------------------------------
setup_python() {
    log_info "Checking Python installation..."

    PYTHON_CMD=""
    for candidate in python3 python; do
        if check_command "${candidate}"; then
            PY_VER="$("${candidate}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
            if python3 -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" 2>/dev/null; then
                PYTHON_CMD="${candidate}"
                break
            fi
        fi
    done

    if [[ -z "${PYTHON_CMD}" ]]; then
        log_warn "Python >= ${MIN_PYTHON} not found. Attempting to install..."
        OS="$(detect_os)"
        if [[ "${OS}" == "macos" ]]; then
            if check_command brew; then
                brew install python@3.11
            else
                log_error "Install Homebrew first: https://brew.sh"
                exit 1
            fi
        else
            sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip python3-venv
        fi
        PYTHON_CMD="python3"
    fi

    log_ok "Python: ${PYTHON_CMD} ($("${PYTHON_CMD}" --version 2>&1))"

    # Create virtual environment
    log_info "Creating virtual environment..."
    "${PYTHON_CMD}" -m venv "${VENV_DIR}"
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"

    pip install --upgrade pip --quiet
    pip install --quiet \
        PyPDF2 \
        ollama \
        pyautogui \
        Pillow \
        aiohttp \
        aiofiles \
        pydantic \
        python-dotenv \
        beautifulsoup4 \
        requests

    log_ok "Python virtual environment ready at ${VENV_DIR}"
}

# ---------------------------------------------------------------------------
# Go installation
# ---------------------------------------------------------------------------
setup_go() {
    log_info "Checking Go installation..."

    if check_command go; then
        GO_VER="$(go version | awk '{print $3}')"
        log_ok "Go already installed: ${GO_VER}"
        return
    fi

    log_info "Installing Go..."
    OS="$(detect_os)"
    ARCH="$(detect_arch)"

    GO_VERSION="1.22.2"
    if [[ "${OS}" == "macos" ]]; then
        GO_PKG="go${GO_VERSION}.darwin-${ARCH}.tar.gz"
    else
        GO_PKG="go${GO_VERSION}.linux-${ARCH}.tar.gz"
    fi

    GO_URL="https://go.dev/dl/${GO_PKG}"
    TEMP_DIR="$(mktemp -d)"
    curl -fsSL "${GO_URL}" -o "${TEMP_DIR}/${GO_PKG}"
    sudo tar -C /usr/local -xzf "${TEMP_DIR}/${GO_PKG}"
    rm -rf "${TEMP_DIR}"

    export PATH="/usr/local/go/bin:${PATH}"
    # Add to shell profile
    SHELL_RC="${HOME}/.bashrc"
    [[ -f "${HOME}/.zshrc" ]] && SHELL_RC="${HOME}/.zshrc"
    if ! grep -q '/usr/local/go/bin' "${SHELL_RC}" 2>/dev/null; then
        echo 'export PATH="/usr/local/go/bin:${PATH}"' >> "${SHELL_RC}"
    fi

    log_ok "Go installed: $(go version)"
}

# ---------------------------------------------------------------------------
# Ollama installation
# ---------------------------------------------------------------------------
setup_ollama() {
    log_info "Checking Ollama installation..."

    if check_command ollama; then
        log_ok "Ollama already installed."
    else
        log_info "Installing Ollama..."
        curl -fsSL https://ollama.com/install.sh | sh
        log_ok "Ollama installed."
    fi

    # Start Ollama in the background if not running
    if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
        log_info "Starting Ollama daemon..."
        ollama serve &>/dev/null &
        OLLAMA_PID=$!
        # Wait for it to be ready (up to 30s)
        for i in $(seq 1 30); do
            if curl -sf http://localhost:11434/api/tags &>/dev/null; then
                break
            fi
            sleep 1
        done
    fi

    # Pull the model
    log_info "Pulling ${OLLAMA_MODEL} (this may take several minutes)..."
    ollama pull "${OLLAMA_MODEL}"
    log_ok "Model ${OLLAMA_MODEL} ready."
}

# ---------------------------------------------------------------------------
# nanobot installation
# ---------------------------------------------------------------------------
setup_nanobot() {
    log_info "Checking nanobot installation..."

    if check_command nanobot; then
        log_ok "nanobot already installed."
        return
    fi

    log_info "Installing nanobot..."
    OS="$(detect_os)"
    ARCH="$(detect_arch)"

    if check_command go; then
        go install github.com/nano-bot/nanobot@latest 2>/dev/null || true
    fi

    # If go install didn't work, try binary download
    if ! check_command nanobot; then
        NANOBOT_URL="https://github.com/nano-bot/nanobot/releases/latest/download/nanobot-${OS}-${ARCH}"
        NANOBOT_BIN="/usr/local/bin/nanobot"
        if curl -fsSL "${NANOBOT_URL}" -o /tmp/nanobot 2>/dev/null; then
            sudo mv /tmp/nanobot "${NANOBOT_BIN}"
            sudo chmod +x "${NANOBOT_BIN}"
            log_ok "nanobot installed to ${NANOBOT_BIN}"
        else
            log_warn "Could not download nanobot binary. You may need to install manually."
            log_warn "See: https://github.com/nano-bot/nanobot"
        fi
    fi
}

# ---------------------------------------------------------------------------
# Node.js check (needed for MCP servers)
# ---------------------------------------------------------------------------
setup_node() {
    log_info "Checking Node.js..."

    if check_command node && check_command npx; then
        log_ok "Node.js found: $(node --version)"
        return
    fi

    log_info "Installing Node.js via nvm..."
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

    export NVM_DIR="${HOME}/.nvm"
    # shellcheck disable=SC1091
    [ -s "${NVM_DIR}/nvm.sh" ] && source "${NVM_DIR}/nvm.sh"

    nvm install --lts
    nvm use --lts

    log_ok "Node.js installed: $(node --version)"
}

# ---------------------------------------------------------------------------
# Copy project files to install directory
# ---------------------------------------------------------------------------
copy_project_files() {
    log_info "Copying project files to ${INSTALL_DIR}..."

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # Copy agent files
    cp -f "${SCRIPT_DIR}/agent/"*.py "${INSTALL_DIR}/agent/" 2>/dev/null || true

    # Copy config
    cp -f "${SCRIPT_DIR}/config/nanobot.json" "${INSTALL_DIR}/config/" 2>/dev/null || true

    # Copy security policy
    cp -f "${SCRIPT_DIR}/security/policy.yaml" "${INSTALL_DIR}/security/" 2>/dev/null || true

    # Copy scripts
    cp -f "${SCRIPT_DIR}/scripts/run.sh" "${INSTALL_DIR}/scripts/" 2>/dev/null || true
    chmod +x "${INSTALL_DIR}/scripts/run.sh" 2>/dev/null || true

    # Copy sample files if present
    cp -f "${SCRIPT_DIR}/samples/"* "${INSTALL_DIR}/samples/" 2>/dev/null || true

    log_ok "Project files copied."
}

# ---------------------------------------------------------------------------
# Set up AgentGuard security
# ---------------------------------------------------------------------------
setup_security() {
    log_info "Configuring AgentGuard security policy..."

    POLICY_FILE="${SECURITY_DIR}/policy.yaml"

    if [[ ! -f "${POLICY_FILE}" ]]; then
        log_warn "policy.yaml not found in ${SECURITY_DIR}. It will be created by copy step."
    fi

    # Create a shell wrapper that enforces the policy
    GUARD_SCRIPT="${INSTALL_DIR}/scripts/agentguard.sh"
    cat > "${GUARD_SCRIPT}" << 'GUARD_EOF'
#!/usr/bin/env bash
# AgentGuard - Command interceptor for AI safety
# Usage: agentguard.sh <command> [args...]

set -euo pipefail

LOG_FILE="${HOME}/ai-assistant/logs/agentguard.log"
POLICY_FILE="${HOME}/ai-assistant/security/policy.yaml"

BLOCKED_PATTERNS=(
    "rm -rf /"
    "rm -rf /*"
    "dd if=/dev/zero"
    "mkfs"
    "sudo"
    "chmod 777"
    ":(){:|:&};:"
    "curl.*|.*sh"
    "wget.*|.*sh"
)

BLOCKED_PATHS=(
    "${HOME}/.ssh"
    "${HOME}/.aws"
    "${HOME}/.config/gcloud"
    "${HOME}/.gnupg"
    "${HOME}/.env"
)

COMMAND="$*"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# Log the command
echo "${TIMESTAMP} RECEIVED: ${COMMAND}" >> "${LOG_FILE}"

# Check blocked patterns
for pattern in "${BLOCKED_PATTERNS[@]}"; do
    if echo "${COMMAND}" | grep -qiE "${pattern}"; then
        echo "${TIMESTAMP} BLOCKED: ${COMMAND} (matched pattern: ${pattern})" >> "${LOG_FILE}"
        echo "⛔ BLOCKED by AgentGuard: Command matches dangerous pattern '${pattern}'"
        exit 1
    fi
done

# Check blocked paths
for blocked_path in "${BLOCKED_PATHS[@]}"; do
    if echo "${COMMAND}" | grep -qi "${blocked_path}"; then
        echo "${TIMESTAMP} BLOCKED: ${COMMAND} (accesses ${blocked_path})" >> "${LOG_FILE}"
        echo "⛔ BLOCKED by AgentGuard: Command accesses protected path '${blocked_path}'"
        exit 1
    fi
done

# Prompt for unknown / potentially dangerous commands
SAFE_COMMANDS="^(ls|cat|echo|python|python3|pip|ollama|nanobot|npx|node|cd|pwd|mkdir|cp|mv|head|tail|grep|wc|date|find)"
if ! echo "${COMMAND}" | grep -qE "${SAFE_COMMANDS}"; then
    echo "${TIMESTAMP} PROMPT: ${COMMAND}" >> "${LOG_FILE}"
    echo ""
    echo "⚠️  AgentGuard: Unknown command detected"
    echo "   Command: ${COMMAND}"
    echo ""
    read -rp "Allow this command? [y/N] " response
    if [[ ! "${response}" =~ ^[Yy]$ ]]; then
        echo "${TIMESTAMP} DENIED_BY_USER: ${COMMAND}" >> "${LOG_FILE}"
        echo "❌ Command denied by user."
        exit 1
    fi
    echo "${TIMESTAMP} APPROVED_BY_USER: ${COMMAND}" >> "${LOG_FILE}"
fi

# Execute the command
echo "${TIMESTAMP} EXECUTING: ${COMMAND}" >> "${LOG_FILE}"
eval "${COMMAND}"
EXIT_CODE=$?
echo "${TIMESTAMP} COMPLETED (exit=${EXIT_CODE}): ${COMMAND}" >> "${LOG_FILE}"
exit ${EXIT_CODE}
GUARD_EOF

    chmod +x "${GUARD_SCRIPT}"

    # Create a convenience alias
    SHELL_RC="${HOME}/.bashrc"
    [[ -f "${HOME}/.zshrc" ]] && SHELL_RC="${HOME}/.zshrc"
    if ! grep -q 'alias agentguard=' "${SHELL_RC}" 2>/dev/null; then
        echo "alias agentguard='${GUARD_SCRIPT}'" >> "${SHELL_RC}"
    fi

    log_ok "AgentGuard configured."
}

# ---------------------------------------------------------------------------
# Final verification
# ---------------------------------------------------------------------------
verify_installation() {
    log_info "Verifying installation..."

    ERRORS=0

    # Python venv
    if [[ -f "${VENV_DIR}/bin/activate" ]]; then
        log_ok "Python virtual environment"
    else
        log_error "Python virtual environment missing"
        ((ERRORS++))
    fi

    # Ollama
    if check_command ollama; then
        log_ok "Ollama CLI"
    else
        log_error "Ollama not found"
        ((ERRORS++))
    fi

    # Ollama model
    if ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL%%:*}"; then
        log_ok "Ollama model: ${OLLAMA_MODEL}"
    else
        log_warn "Ollama model ${OLLAMA_MODEL} may not be pulled yet"
    fi

    # Config files
    if [[ -f "${INSTALL_DIR}/config/nanobot.json" ]]; then
        log_ok "nanobot config"
    else
        log_warn "nanobot.json not found"
    fi

    if [[ -f "${INSTALL_DIR}/security/policy.yaml" ]]; then
        log_ok "Security policy"
    else
        log_warn "policy.yaml not found"
    fi

    if [[ -f "${INSTALL_DIR}/agent/bid_agent.py" ]]; then
        log_ok "Bid agent"
    else
        log_warn "bid_agent.py not found"
    fi

    echo ""
    if (( ERRORS == 0 )); then
        log_ok "Installation complete! 🎉"
    else
        log_error "Installation completed with ${ERRORS} error(s)."
    fi

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Quick Start:"
    echo "    1. source ${VENV_DIR}/bin/activate"
    echo "    2. bash ${INSTALL_DIR}/scripts/run.sh"
    echo "    3. Open http://localhost:3000 in your browser"
    echo ""
    echo "  Process a bid:"
    echo "    python ${INSTALL_DIR}/agent/bid_agent.py ~/Downloads/bid.pdf"
    echo ""
    echo "  With AgentGuard:"
    echo "    agentguard python ${INSTALL_DIR}/agent/bid_agent.py ~/Downloads/bid.pdf"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    echo ""
    echo "╔══════════════════════════════════════════════════╗"
    echo "║  Autonomous Bid Processing Assistant - Installer ║"
    echo "╚══════════════════════════════════════════════════╝"
    echo ""

    preflight_checks
    setup_directories
    setup_python
    setup_go
    setup_ollama
    setup_nanobot
    setup_node
    copy_project_files
    setup_security
    verify_installation
}

main "$@"
