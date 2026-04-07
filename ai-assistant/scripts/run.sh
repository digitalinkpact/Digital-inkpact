#!/usr/bin/env bash
# =============================================================================
# Bid Processing Assistant - Run Script (macOS/Linux)
#
# Starts all services:
#   1. Ollama daemon (if not already running)
#   2. nanobot web interface on port 3000
#   3. Displays status and log locations
#
# Usage: bash run.sh [--headless]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${INSTALL_DIR}/config/nanobot.json"
LOG_DIR="${INSTALL_DIR}/logs"
VENV_DIR="${INSTALL_DIR}/venv"
OLLAMA_PORT=11434
NANOBOT_PORT=3000

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
cleanup() {
    log_info "Shutting down services..."
    if [[ -n "${NANOBOT_PID:-}" ]]; then
        kill "${NANOBOT_PID}" 2>/dev/null || true
    fi
    log_info "Done."
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Pre-checks
# ---------------------------------------------------------------------------
check_prereqs() {
    if [[ ! -d "${INSTALL_DIR}" ]]; then
        log_error "Installation directory not found: ${INSTALL_DIR}"
        log_error "Run install.sh first."
        exit 1
    fi

    if [[ ! -f "${CONFIG_FILE}" ]]; then
        log_error "Config file not found: ${CONFIG_FILE}"
        exit 1
    fi

    if ! command -v ollama &>/dev/null; then
        log_error "ollama not found on PATH. Run install.sh first."
        exit 1
    fi

    mkdir -p "${LOG_DIR}"
}

# ---------------------------------------------------------------------------
# Start Ollama
# ---------------------------------------------------------------------------
start_ollama() {
    log_info "Checking Ollama daemon..."

    if curl -sf "http://localhost:${OLLAMA_PORT}/api/tags" &>/dev/null; then
        log_ok "Ollama already running on port ${OLLAMA_PORT}"
    else
        log_info "Starting Ollama daemon..."
        ollama serve >> "${LOG_DIR}/ollama.log" 2>&1 &
        OLLAMA_PID=$!

        # Wait up to 30 seconds
        for i in $(seq 1 30); do
            if curl -sf "http://localhost:${OLLAMA_PORT}/api/tags" &>/dev/null; then
                log_ok "Ollama started (PID ${OLLAMA_PID})"
                return
            fi
            sleep 1
        done

        log_error "Ollama failed to start within 30 seconds."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Verify model
# ---------------------------------------------------------------------------
verify_model() {
    log_info "Verifying LLM model..."

    MODEL=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['llm']['model'])" 2>/dev/null || echo "mistral:7b")

    if ollama list 2>/dev/null | grep -q "${MODEL%%:*}"; then
        log_ok "Model ${MODEL} is available"
    else
        log_warn "Model ${MODEL} not found. Pulling now..."
        ollama pull "${MODEL}"
        log_ok "Model ${MODEL} ready"
    fi
}

# ---------------------------------------------------------------------------
# Activate Python venv
# ---------------------------------------------------------------------------
activate_venv() {
    if [[ -f "${VENV_DIR}/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "${VENV_DIR}/bin/activate"
        log_ok "Python virtual environment activated"
    else
        log_warn "No virtual environment found at ${VENV_DIR}. Using system Python."
    fi
}

# ---------------------------------------------------------------------------
# Start nanobot
# ---------------------------------------------------------------------------
start_nanobot() {
    log_info "Starting web interface..."

    # Kill any stale process on our port
    local stale_pid
    stale_pid=$(lsof -ti :${NANOBOT_PORT} 2>/dev/null || true)
    if [[ -n "${stale_pid}" ]]; then
        log_warn "Killing stale process on port ${NANOBOT_PORT} (PID ${stale_pid})"
        kill ${stale_pid} 2>/dev/null || true
        sleep 1
    fi

    start_fallback_interface
}

# ---------------------------------------------------------------------------
# Fallback: Python web chat server with full agent support
# ---------------------------------------------------------------------------
start_fallback_interface() {
    MODEL=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['llm']['model'])" 2>/dev/null || echo "llama3.2:3b")
    python3 "${SCRIPT_DIR}/web_server.py" "${INSTALL_DIR}" "${MODEL}" >> "${LOG_DIR}/nanobot.log" 2>&1 &

    NANOBOT_PID=$!
    sleep 1
    log_ok "Web interface started on port ${NANOBOT_PORT}"
}

# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------
show_status() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Bid Processing Assistant - Running"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  Web Interface:  http://localhost:${NANOBOT_PORT}"
    echo "  Ollama API:     http://localhost:${OLLAMA_PORT}"
    echo ""
    echo "  Logs:"
    echo "    Ollama:       ${LOG_DIR}/ollama.log"
    echo "    nanobot:      ${LOG_DIR}/nanobot.log"
    echo "    Bid Agent:    ${LOG_DIR}/bid_agent.log"
    echo "    AgentGuard:   ${LOG_DIR}/agentguard.log"
    echo ""
    echo "  Process a bid:"
    echo "    python ${INSTALL_DIR}/agent/bid_agent.py ~/Downloads/bid.pdf"
    echo ""
    echo "  Press Ctrl+C to stop all services."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    echo ""
    echo "Starting Bid Processing Assistant..."
    echo ""

    check_prereqs
    activate_venv
    start_ollama
    verify_model
    start_nanobot
    show_status

    # Keep running until interrupted
    wait
}

main "$@"
