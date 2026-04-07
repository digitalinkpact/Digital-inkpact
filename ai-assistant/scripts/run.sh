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
MAX_PORT_ATTEMPTS=10

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

is_port_free() {
    local port="$1"
    if lsof -ti :"${port}" >/dev/null 2>&1; then
        return 1
    fi
    return 0
}

cleanup_stale_web_server_on_port() {
    local port="$1"
    local pids
    pids=$(lsof -ti :"${port}" 2>/dev/null || true)
    if [[ -z "${pids}" ]]; then
        return
    fi

    for pid in ${pids}; do
        local cmd
        cmd=$(ps -p "${pid}" -o args= 2>/dev/null || true)
        if [[ "${cmd}" == *"${SCRIPT_DIR}/web_server.py"* ]]; then
            log_warn "Killing stale assistant process on port ${port} (PID ${pid})"
            kill "${pid}" 2>/dev/null || true
        fi
    done
}

select_nanobot_port() {
    local preferred_port="$1"
    local attempts="$2"
    local candidate

    for i in $(seq 0 $((attempts - 1))); do
        candidate=$((preferred_port + i))
        if is_port_free "${candidate}"; then
            echo "${candidate}"
            return 0
        fi
    done

    return 1
}

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

    # If our own old web server is still around, clear it first.
    cleanup_stale_web_server_on_port "${NANOBOT_PORT}"
    sleep 1

    local selected_port
    selected_port=$(select_nanobot_port "${NANOBOT_PORT}" "${MAX_PORT_ATTEMPTS}" || true)
    if [[ -z "${selected_port}" ]]; then
        log_error "Could not find a free port in range ${NANOBOT_PORT}-$((NANOBOT_PORT + MAX_PORT_ATTEMPTS - 1))."
        lsof -iTCP:${NANOBOT_PORT}-$((NANOBOT_PORT + MAX_PORT_ATTEMPTS - 1)) -sTCP:LISTEN -n -P || true
        exit 1
    fi

    if [[ "${selected_port}" != "${NANOBOT_PORT}" ]]; then
        log_warn "Port ${NANOBOT_PORT} is busy. Falling back to port ${selected_port}."
    fi

    NANOBOT_PORT="${selected_port}"

    start_fallback_interface
}

# ---------------------------------------------------------------------------
# Fallback: Python web chat server with full agent support
# ---------------------------------------------------------------------------
start_fallback_interface() {
    MODEL=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['llm']['model'])" 2>/dev/null || echo "llama3.2:3b")
    python3 "${SCRIPT_DIR}/web_server.py" "${INSTALL_DIR}" "${MODEL}" "${NANOBOT_PORT}" >> "${LOG_DIR}/nanobot.log" 2>&1 &

    NANOBOT_PID=$!

    # Verify the server is actually reachable before reporting success.
    for i in $(seq 1 15); do
        if curl -sf "http://127.0.0.1:${NANOBOT_PORT}/health" >/dev/null 2>&1; then
            log_ok "Web interface started on port ${NANOBOT_PORT}"
            return
        fi

        if ! kill -0 "${NANOBOT_PID}" 2>/dev/null; then
            break
        fi

        sleep 1
    done

    log_error "Web interface failed to start on port ${NANOBOT_PORT}."
    log_error "Last 20 lines from ${LOG_DIR}/nanobot.log:"
    tail -n 20 "${LOG_DIR}/nanobot.log" 2>/dev/null || true
    exit 1
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
