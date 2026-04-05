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

INSTALL_DIR="${HOME}/ai-assistant"
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
    log_info "Starting nanobot web interface..."

    if command -v nanobot &>/dev/null; then
        nanobot serve --config "${CONFIG_FILE}" >> "${LOG_DIR}/nanobot.log" 2>&1 &
        NANOBOT_PID=$!
        sleep 2

        if kill -0 "${NANOBOT_PID}" 2>/dev/null; then
            log_ok "nanobot started (PID ${NANOBOT_PID}) on port ${NANOBOT_PORT}"
        else
            log_warn "nanobot may have failed to start. Check ${LOG_DIR}/nanobot.log"
        fi
    else
        log_warn "nanobot not found. Starting fallback Python HTTP interface..."
        start_fallback_interface
    fi
}

# ---------------------------------------------------------------------------
# Fallback: simple Python chat interface
# ---------------------------------------------------------------------------
start_fallback_interface() {
    python3 - <<'PYEOF' &
import http.server
import json
import socketserver
import urllib.parse
import sys
import os

sys.path.insert(0, os.path.expanduser("~/ai-assistant/agent"))

PORT = 3000
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bid Processing Assistant</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }
.header { background: #16213e; padding: 16px 24px; border-bottom: 1px solid #0f3460; }
.header h1 { font-size: 18px; color: #e94560; }
.header p { font-size: 12px; color: #888; margin-top: 4px; }
.chat { flex: 1; overflow-y: auto; padding: 24px; }
.msg { margin-bottom: 16px; max-width: 80%; }
.msg.user { margin-left: auto; }
.msg .bubble { padding: 12px 16px; border-radius: 12px; font-size: 14px; line-height: 1.5; }
.msg.user .bubble { background: #0f3460; }
.msg.bot .bubble { background: #16213e; border: 1px solid #0f3460; }
.input-area { padding: 16px 24px; background: #16213e; border-top: 1px solid #0f3460; display: flex; gap: 12px; }
.input-area input { flex: 1; background: #1a1a2e; border: 1px solid #0f3460; color: #e0e0e0; padding: 12px 16px; border-radius: 8px; font-size: 14px; outline: none; }
.input-area input:focus { border-color: #e94560; }
.input-area button { background: #e94560; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 14px; }
.input-area button:hover { background: #c73650; }
.status { font-size: 11px; color: #4a4a6a; text-align: center; padding: 8px; }
</style>
</head>
<body>
<div class="header">
  <h1>Bid Processing Assistant</h1>
  <p>Local LLM &bull; Secure &bull; Offline</p>
</div>
<div class="chat" id="chat">
  <div class="msg bot"><div class="bubble">Ready. Drop a bid PDF or ask me anything about bid processing.</div></div>
</div>
<div class="input-area">
  <input type="text" id="input" placeholder="Type a message or paste a file path..." autofocus>
  <button onclick="send()">Send</button>
</div>
<div class="status">Connected to Ollama (localhost:11434) | AgentGuard active</div>
<script>
const chat = document.getElementById('chat');
const input = document.getElementById('input');
input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
async function send() {
  const msg = input.value.trim();
  if (!msg) return;
  addMsg(msg, 'user');
  input.value = '';
  try {
    const r = await fetch('/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({message: msg})});
    const data = await r.json();
    addMsg(data.response || 'No response.', 'bot');
  } catch(e) {
    addMsg('Error: ' + e.message, 'bot');
  }
}
function addMsg(text, role) {
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  d.innerHTML = '<div class="bubble">' + text.replace(/\\n/g,'<br>') + '</div>';
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
}
</script>
</body>
</html>"""

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def do_POST(self):
        if self.path == "/chat":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            message = body.get("message", "")
            try:
                import ollama as _ollama
                resp = _ollama.chat(model="mistral:7b", messages=[{"role":"user","content":message}])
                answer = resp["message"]["content"]
            except Exception as e:
                answer = f"LLM error: {e}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"response": answer}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default logging

with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
    print(f"Fallback web UI running on http://127.0.0.1:{PORT}")
    httpd.serve_forever()
PYEOF

    NANOBOT_PID=$!
    sleep 1
    log_ok "Fallback web interface started on port ${NANOBOT_PORT}"
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
