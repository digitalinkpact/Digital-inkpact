# =============================================================================
# Autonomous Bid Processing Assistant - Installer (Windows)
#
# One-click installer for Windows that sets up all dependencies:
#   - Go (for nanobot)
#   - Ollama (local LLM)
#   - nanobot (lightweight chat interface with MCP)
#   - Python virtual environment with required packages
#   - AgentGuard security policy
#   - Directory structure and configuration
#
# Usage: Right-click -> Run with PowerShell  (or:  powershell -ExecutionPolicy Bypass -File install.ps1)
# =============================================================================

#Requires -Version 5.1
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
$INSTALL_DIR   = Join-Path $env:USERPROFILE "ai-assistant"
$VENV_DIR      = Join-Path $INSTALL_DIR "venv"
$LOG_DIR       = Join-Path $INSTALL_DIR "logs"
$CONFIG_DIR    = Join-Path $INSTALL_DIR "config"
$SECURITY_DIR  = Join-Path $INSTALL_DIR "security"
$OLLAMA_MODEL  = "mistral:7b"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Status  { param($msg) Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-Ok      { param($msg) Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Warn    { param($msg) Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Err     { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Test-CommandExists {
    param([string]$Command)
    $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------
function Initialize-Directories {
    Write-Status "Creating directory structure at $INSTALL_DIR ..."

    $dirs = @(
        $INSTALL_DIR,
        (Join-Path $INSTALL_DIR "agent"),
        (Join-Path $INSTALL_DIR "config"),
        (Join-Path $INSTALL_DIR "scripts"),
        (Join-Path $INSTALL_DIR "security"),
        (Join-Path $INSTALL_DIR "logs"),
        (Join-Path $INSTALL_DIR "models"),
        (Join-Path $INSTALL_DIR "mcp"),
        (Join-Path $INSTALL_DIR "samples"),
        (Join-Path $env:USERPROFILE "Documents\Bids")
    )
    foreach ($d in $dirs) {
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    }

    Write-Ok "Directories created."
}

# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------
function Install-Python {
    Write-Status "Checking Python installation..."

    $pythonCmd = $null
    foreach ($candidate in @("python", "python3", "py")) {
        if (Test-CommandExists $candidate) {
            $ver = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver -and [version]$ver -ge [version]"3.9") {
                $pythonCmd = $candidate
                break
            }
        }
    }

    if (-not $pythonCmd) {
        Write-Status "Installing Python via winget..."
        winget install Python.Python.3.11 --accept-source-agreements --accept-package-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        $pythonCmd = "python"
    }

    Write-Ok "Python: $pythonCmd ($(& $pythonCmd --version 2>&1))"

    Write-Status "Creating virtual environment..."
    & $pythonCmd -m venv $VENV_DIR
    $activateScript = Join-Path $VENV_DIR "Scripts\Activate.ps1"
    . $activateScript

    pip install --upgrade pip --quiet
    pip install --quiet `
        PyPDF2 `
        ollama `
        pyautogui `
        Pillow `
        aiohttp `
        aiofiles `
        pydantic `
        python-dotenv `
        beautifulsoup4 `
        requests

    Write-Ok "Python virtual environment ready at $VENV_DIR"
}

# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------
function Install-Go {
    Write-Status "Checking Go installation..."

    if (Test-CommandExists go) {
        Write-Ok "Go already installed: $(go version)"
        return
    }

    Write-Status "Installing Go via winget..."
    winget install GoLang.Go --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

    if (Test-CommandExists go) {
        Write-Ok "Go installed: $(go version)"
    } else {
        Write-Warn "Go installed but may require a terminal restart to appear on PATH."
    }
}

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
function Install-Ollama {
    Write-Status "Checking Ollama installation..."

    if (Test-CommandExists ollama) {
        Write-Ok "Ollama already installed."
    } else {
        Write-Status "Installing Ollama..."
        $installerUrl = "https://ollama.com/download/OllamaSetup.exe"
        $installerPath = Join-Path $env:TEMP "OllamaSetup.exe"
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
        Start-Process -FilePath $installerPath -ArgumentList "/S" -Wait
        Remove-Item $installerPath -Force
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        Write-Ok "Ollama installed."
    }

    # Start Ollama if not already running
    try {
        $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -ErrorAction Stop
    } catch {
        Write-Status "Starting Ollama daemon..."
        Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 5
    }

    Write-Status "Pulling $OLLAMA_MODEL (this may take several minutes)..."
    ollama pull $OLLAMA_MODEL
    Write-Ok "Model $OLLAMA_MODEL ready."
}

# ---------------------------------------------------------------------------
# nanobot
# ---------------------------------------------------------------------------
function Install-Nanobot {
    Write-Status "Checking nanobot installation..."

    if (Test-CommandExists nanobot) {
        Write-Ok "nanobot already installed."
        return
    }

    Write-Status "Installing nanobot..."
    if (Test-CommandExists go) {
        go install github.com/nano-bot/nanobot@latest 2>$null
    }

    if (-not (Test-CommandExists nanobot)) {
        $nanobotUrl = "https://github.com/nano-bot/nanobot/releases/latest/download/nanobot-windows-amd64.exe"
        $nanobotPath = Join-Path $env:LOCALAPPDATA "nanobot\nanobot.exe"
        New-Item -ItemType Directory -Path (Split-Path $nanobotPath) -Force | Out-Null
        try {
            Invoke-WebRequest -Uri $nanobotUrl -OutFile $nanobotPath -UseBasicParsing
            $current = [Environment]::GetEnvironmentVariable("Path", "User")
            if ($current -notlike "*nanobot*") {
                [Environment]::SetEnvironmentVariable("Path", "$current;$(Split-Path $nanobotPath)", "User")
            }
            Write-Ok "nanobot installed to $nanobotPath"
        } catch {
            Write-Warn "Could not download nanobot. You may need to install manually."
        }
    }
}

# ---------------------------------------------------------------------------
# Node.js
# ---------------------------------------------------------------------------
function Install-Node {
    Write-Status "Checking Node.js..."

    if ((Test-CommandExists node) -and (Test-CommandExists npx)) {
        Write-Ok "Node.js found: $(node --version)"
        return
    }

    Write-Status "Installing Node.js via winget..."
    winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    Write-Ok "Node.js installed."
}

# ---------------------------------------------------------------------------
# Copy project files
# ---------------------------------------------------------------------------
function Copy-ProjectFiles {
    Write-Status "Copying project files..."

    $scriptRoot = $PSScriptRoot
    if (-not $scriptRoot) { $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }

    # Copy agent files
    $agentSrc = Join-Path $scriptRoot "agent"
    if (Test-Path $agentSrc) {
        Copy-Item "$agentSrc\*.py" -Destination (Join-Path $INSTALL_DIR "agent") -Force
    }

    # Copy config
    $configSrc = Join-Path $scriptRoot "config\nanobot.json"
    if (Test-Path $configSrc) {
        Copy-Item $configSrc -Destination (Join-Path $INSTALL_DIR "config") -Force
    }

    # Copy security policy
    $policySrc = Join-Path $scriptRoot "security\policy.yaml"
    if (Test-Path $policySrc) {
        Copy-Item $policySrc -Destination (Join-Path $INSTALL_DIR "security") -Force
    }

    # Copy scripts
    $runSrc = Join-Path $scriptRoot "scripts\run.ps1"
    if (Test-Path $runSrc) {
        Copy-Item $runSrc -Destination (Join-Path $INSTALL_DIR "scripts") -Force
    }

    Write-Ok "Project files copied."
}

# ---------------------------------------------------------------------------
# AgentGuard security
# ---------------------------------------------------------------------------
function Initialize-Security {
    Write-Status "Configuring AgentGuard security policy..."

    $guardScript = Join-Path $INSTALL_DIR "scripts\agentguard.ps1"

    @'
# AgentGuard - Command interceptor for AI safety (Windows)
# Usage: .\agentguard.ps1 <command> [args...]

param([Parameter(ValueFromRemainingArguments)][string[]]$CommandArgs)

$ErrorActionPreference = "Stop"
$LogFile  = Join-Path $env:USERPROFILE "ai-assistant\logs\agentguard.log"
$Command  = $CommandArgs -join " "
$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

# Ensure log directory exists
$logDir = Split-Path $LogFile
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

Add-Content -Path $LogFile -Value "$Timestamp RECEIVED: $Command"

# Blocked patterns
$BlockedPatterns = @(
    "rm\s+-rf\s+/",
    "Remove-Item.*-Recurse.*C:\\",
    "Format-Volume",
    "Clear-Disk",
    "sudo",
    "chmod\s+777",
    "Invoke-Expression.*http"
)

# Blocked paths
$BlockedPaths = @(
    (Join-Path $env:USERPROFILE ".ssh"),
    (Join-Path $env:USERPROFILE ".aws"),
    (Join-Path $env:USERPROFILE ".config\gcloud"),
    ".env"
)

foreach ($pattern in $BlockedPatterns) {
    if ($Command -match $pattern) {
        Add-Content -Path $LogFile -Value "$Timestamp BLOCKED: $Command (pattern: $pattern)"
        Write-Host "BLOCKED by AgentGuard: Command matches dangerous pattern '$pattern'" -ForegroundColor Red
        exit 1
    }
}

foreach ($blocked in $BlockedPaths) {
    if ($Command -like "*$blocked*") {
        Add-Content -Path $LogFile -Value "$Timestamp BLOCKED: $Command (path: $blocked)"
        Write-Host "BLOCKED by AgentGuard: Command accesses protected path '$blocked'" -ForegroundColor Red
        exit 1
    }
}

# Safe command prefixes
$SafePrefixes = @("dir", "type", "echo", "python", "pip", "ollama", "nanobot", "npx", "node", "cd", "mkdir", "copy")
$isSafe = $false
foreach ($prefix in $SafePrefixes) {
    if ($Command -match "^\s*$prefix\b") { $isSafe = $true; break }
}

if (-not $isSafe) {
    Add-Content -Path $LogFile -Value "$Timestamp PROMPT: $Command"
    Write-Host ""
    Write-Host "AgentGuard: Unknown command detected" -ForegroundColor Yellow
    Write-Host "  Command: $Command"
    $response = Read-Host "Allow this command? [y/N]"
    if ($response -notin @("y", "Y", "yes")) {
        Add-Content -Path $LogFile -Value "$Timestamp DENIED_BY_USER: $Command"
        Write-Host "Command denied by user." -ForegroundColor Red
        exit 1
    }
    Add-Content -Path $LogFile -Value "$Timestamp APPROVED_BY_USER: $Command"
}

Add-Content -Path $LogFile -Value "$Timestamp EXECUTING: $Command"
Invoke-Expression $Command
$exitCode = $LASTEXITCODE
Add-Content -Path $LogFile -Value "$Timestamp COMPLETED (exit=$exitCode): $Command"
exit $exitCode
'@ | Set-Content -Path $guardScript -Encoding UTF8

    Write-Ok "AgentGuard configured."
}

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
function Test-Installation {
    Write-Status "Verifying installation..."
    $errors = 0

    if (Test-Path (Join-Path $VENV_DIR "Scripts\Activate.ps1")) {
        Write-Ok "Python virtual environment"
    } else {
        Write-Err "Python virtual environment missing"; $errors++
    }

    if (Test-CommandExists ollama) {
        Write-Ok "Ollama CLI"
    } else {
        Write-Err "Ollama not found"; $errors++
    }

    if (Test-Path (Join-Path $CONFIG_DIR "nanobot.json")) {
        Write-Ok "nanobot config"
    } else {
        Write-Warn "nanobot.json not found"
    }

    if (Test-Path (Join-Path $SECURITY_DIR "policy.yaml")) {
        Write-Ok "Security policy"
    } else {
        Write-Warn "policy.yaml not found"
    }

    Write-Host ""
    if ($errors -eq 0) {
        Write-Ok "Installation complete!"
    } else {
        Write-Err "Installation completed with $errors error(s)."
    }

    Write-Host ""
    Write-Host "=============================================="
    Write-Host "  Quick Start:"
    Write-Host "    1. . $VENV_DIR\Scripts\Activate.ps1"
    Write-Host "    2. . $INSTALL_DIR\scripts\run.ps1"
    Write-Host "    3. Open http://localhost:3000"
    Write-Host ""
    Write-Host "  Process a bid:"
    Write-Host "    python $INSTALL_DIR\agent\bid_agent.py ~\Downloads\bid.pdf"
    Write-Host "=============================================="
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "========================================================="
Write-Host "  Autonomous Bid Processing Assistant - Windows Installer"
Write-Host "========================================================="
Write-Host ""

Initialize-Directories
Install-Python
Install-Go
Install-Ollama
Install-Nanobot
Install-Node
Copy-ProjectFiles
Initialize-Security
Test-Installation
