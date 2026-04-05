# =============================================================================
# Bid Processing Assistant - Run Script (Windows)
#
# Starts all services:
#   1. Ollama daemon (if not already running)
#   2. nanobot web interface on port 3000
#   3. Displays status and log locations
#
# Usage: powershell -ExecutionPolicy Bypass -File run.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

$INSTALL_DIR  = Join-Path $env:USERPROFILE "ai-assistant"
$CONFIG_FILE  = Join-Path $INSTALL_DIR "config\nanobot.json"
$LOG_DIR      = Join-Path $INSTALL_DIR "logs"
$VENV_DIR     = Join-Path $INSTALL_DIR "venv"
$OLLAMA_PORT  = 11434
$NANOBOT_PORT = 3000

function Write-Status  { param($msg) Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-Ok      { param($msg) Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Warn    { param($msg) Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Err     { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Test-CommandExists {
    param([string]$Command)
    $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

# ---------------------------------------------------------------------------
# Pre-checks
# ---------------------------------------------------------------------------
function Test-Prerequisites {
    if (-not (Test-Path $INSTALL_DIR)) {
        Write-Err "Installation directory not found: $INSTALL_DIR"
        Write-Err "Run install.ps1 first."
        exit 1
    }
    if (-not (Test-Path $CONFIG_FILE)) {
        Write-Err "Config file not found: $CONFIG_FILE"
        exit 1
    }
    if (-not (Test-CommandExists ollama)) {
        Write-Err "ollama not found. Run install.ps1 first."
        exit 1
    }
    if (-not (Test-Path $LOG_DIR)) {
        New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
    }
}

# ---------------------------------------------------------------------------
# Start Ollama
# ---------------------------------------------------------------------------
function Start-OllamaService {
    Write-Status "Checking Ollama daemon..."

    try {
        $null = Invoke-RestMethod -Uri "http://localhost:$OLLAMA_PORT/api/tags" -ErrorAction Stop
        Write-Ok "Ollama already running on port $OLLAMA_PORT"
    } catch {
        Write-Status "Starting Ollama daemon..."
        $logFile = Join-Path $LOG_DIR "ollama.log"
        Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
        Start-Sleep -Seconds 5

        try {
            $null = Invoke-RestMethod -Uri "http://localhost:$OLLAMA_PORT/api/tags" -ErrorAction Stop
            Write-Ok "Ollama started on port $OLLAMA_PORT"
        } catch {
            Write-Err "Ollama failed to start. Check $logFile"
            exit 1
        }
    }
}

# ---------------------------------------------------------------------------
# Verify model
# ---------------------------------------------------------------------------
function Test-Model {
    Write-Status "Verifying LLM model..."

    $config = Get-Content $CONFIG_FILE | ConvertFrom-Json
    $model = $config.llm.model

    $models = ollama list 2>$null
    if ($models -match ($model -split ':')[0]) {
        Write-Ok "Model $model is available"
    } else {
        Write-Warn "Model $model not found. Pulling now..."
        ollama pull $model
        Write-Ok "Model $model ready"
    }
}

# ---------------------------------------------------------------------------
# Activate Python venv
# ---------------------------------------------------------------------------
function Initialize-Venv {
    $activateScript = Join-Path $VENV_DIR "Scripts\Activate.ps1"
    if (Test-Path $activateScript) {
        . $activateScript
        Write-Ok "Python virtual environment activated"
    } else {
        Write-Warn "No virtual environment found. Using system Python."
    }
}

# ---------------------------------------------------------------------------
# Start nanobot (or fallback)
# ---------------------------------------------------------------------------
function Start-NanobotService {
    Write-Status "Starting nanobot web interface..."

    if (Test-CommandExists nanobot) {
        $logFile = Join-Path $LOG_DIR "nanobot.log"
        Start-Process nanobot -ArgumentList "serve", "--config", $CONFIG_FILE `
            -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
        Start-Sleep -Seconds 2
        Write-Ok "nanobot started on port $NANOBOT_PORT"
    } else {
        Write-Warn "nanobot not found. Starting fallback Python interface..."

        $fallbackScript = Join-Path $INSTALL_DIR "scripts\fallback_server.py"

        # Write a minimal fallback server
        @'
import http.server, json, socketserver

PORT = 3000
HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Bid Assistant</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:sans-serif;background:#1a1a2e;color:#e0e0e0;height:100vh;display:flex;flex-direction:column}.header{background:#16213e;padding:16px;border-bottom:1px solid #0f3460}.header h1{font-size:18px;color:#e94560}.chat{flex:1;overflow-y:auto;padding:24px}.msg{margin-bottom:16px;max-width:80%}.msg.user{margin-left:auto}.bubble{padding:12px 16px;border-radius:12px;font-size:14px;line-height:1.5}.msg.user .bubble{background:#0f3460}.msg.bot .bubble{background:#16213e;border:1px solid #0f3460}.input-area{padding:16px;background:#16213e;display:flex;gap:12px}.input-area input{flex:1;background:#1a1a2e;border:1px solid #0f3460;color:#e0e0e0;padding:12px;border-radius:8px;outline:none}.input-area button{background:#e94560;color:white;border:none;padding:12px 24px;border-radius:8px;cursor:pointer}</style></head>
<body><div class="header"><h1>Bid Processing Assistant</h1></div><div class="chat" id="chat"><div class="msg bot"><div class="bubble">Ready.</div></div></div><div class="input-area"><input id="input" placeholder="Type..."><button onclick="send()">Send</button></div>
<script>const c=document.getElementById('chat'),i=document.getElementById('input');i.onkeydown=e=>{if(e.key==='Enter')send()};async function send(){const m=i.value.trim();if(!m)return;add(m,'user');i.value='';try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m})});const d=await r.json();add(d.response,'bot')}catch(e){add('Error: '+e,'bot')}}function add(t,r){const d=document.createElement('div');d.className='msg '+r;d.innerHTML='<div class="bubble">'+t.replace(/\n/g,'<br>')+'</div>';c.appendChild(d);c.scrollTop=c.scrollHeight}</script></body></html>"""

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type","text/html"); self.end_headers(); self.wfile.write(HTML.encode())
    def do_POST(self):
        if self.path=="/chat":
            l=int(self.headers.get("Content-Length",0)); b=json.loads(self.rfile.read(l)) if l else {}
            try:
                import ollama; r=ollama.chat(model="mistral:7b",messages=[{"role":"user","content":b.get("message","")}]); a=r["message"]["content"]
            except Exception as e: a=str(e)
            self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(json.dumps({"response":a}).encode())
    def log_message(self,*a): pass

with socketserver.TCPServer(("127.0.0.1",PORT),H) as s: print(f"http://127.0.0.1:{PORT}"); s.serve_forever()
'@ | Set-Content -Path $fallbackScript -Encoding UTF8

        Start-Process python -ArgumentList $fallbackScript -WindowStyle Hidden
        Start-Sleep -Seconds 2
        Write-Ok "Fallback web interface on port $NANOBOT_PORT"
    }
}

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
function Show-Status {
    Write-Host ""
    Write-Host "================================================"
    Write-Host "  Bid Processing Assistant - Running"
    Write-Host "================================================"
    Write-Host ""
    Write-Host "  Web Interface:  http://localhost:$NANOBOT_PORT"
    Write-Host "  Ollama API:     http://localhost:$OLLAMA_PORT"
    Write-Host ""
    Write-Host "  Logs: $LOG_DIR"
    Write-Host ""
    Write-Host "  Process a bid:"
    Write-Host "    python $INSTALL_DIR\agent\bid_agent.py ~\Downloads\bid.pdf"
    Write-Host ""
    Write-Host "  Press Ctrl+C to stop."
    Write-Host "================================================"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Starting Bid Processing Assistant..."
Write-Host ""

Test-Prerequisites
Initialize-Venv
Start-OllamaService
Test-Model
Start-NanobotService
Show-Status

# Keep the script alive
try {
    while ($true) { Start-Sleep -Seconds 60 }
} finally {
    Write-Status "Shutting down..."
    Get-Process -Name "nanobot" -ErrorAction SilentlyContinue | Stop-Process -Force
}
