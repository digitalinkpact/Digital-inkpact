# Autonomous Bid Processing Assistant

A fully local, zero-cost AI assistant that processes construction bid packages, generates professional quotes, and automates Adobe Photoshop/Illustrator for drawing callouts — all running on your own machine with no API keys required.

## Features

- **100% Local LLM** — Ollama with Mistral 7B (or Llama 3.2 3B for low-RAM systems)
- **PDF Bid Parsing** — Extracts line items, quantities, materials, labor, and deadlines
- **Quote Generation** — Automatic pricing with markup and tax calculations
- **Adobe Automation** — Controls Photoshop/Illustrator for drawing callouts
- **Web Access** — Searches for bid opportunities and material prices
- **Chat Interface** — Lightweight nanobot web UI on port 3000
- **Security First** — AgentGuard blocks dangerous commands, logs everything
- **MCP Integration** — Model Context Protocol for tool interoperability
- **Cross-Platform** — macOS, Windows, and Linux

## Architecture

```
┌────────────────────────────────────────────┐
│               Chat Interface               │
│         nanobot (port 3000)                │
├────────────────────────────────────────────┤
│            AgentGuard (Security)           │
│  ┌──────────┬──────────┬────────────────┐  │
│  │  Deny    │  Allow   │    Prompt      │  │
│  │  Layer   │  Layer   │    Layer       │  │
│  └──────────┴──────────┴────────────────┘  │
├────────────────────────────────────────────┤
│              MCP Tool Layer                │
│  ┌──────────┬──────────┬────────────────┐  │
│  │Filesystem│  Adobe   │  Web Search    │  │
│  │  Server  │  Server  │    Server      │  │
│  └──────────┴──────────┴────────────────┘  │
├────────────────────────────────────────────┤
│           Ollama (Local LLM)               │
│         mistral:7b on port 11434           │
└────────────────────────────────────────────┘
```

## Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM | 8 GB | 16 GB |
| Disk | 5 GB | 10 GB |
| CPU | 4 cores | 8 cores |
| GPU | None | NVIDIA (CUDA) for faster inference |
| OS | macOS 12+, Windows 10+, Ubuntu 22.04+ | — |
| Python | 3.9+ | 3.11+ |

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/digitalinkpact/Digital-inkpact.git
cd Digital-inkpact/ai-assistant
```

### 2. Run the installer

**macOS / Linux:**
```bash
chmod +x install.sh
bash install.sh
```

**Windows (PowerShell as Administrator):**
```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\install.ps1
```

The installer will:
- Install Go, Ollama, nanobot, Node.js, and Python dependencies
- Pull the Mistral 7B model (~4 GB download)
- Set up the AgentGuard security policy
- Create a Python virtual environment

### 3. Start the assistant

**macOS / Linux:**
```bash
bash scripts/run.sh
```

**Windows:**
```powershell
.\scripts\run.ps1
```

### 4. Open the web interface

Navigate to **http://localhost:3000** in your browser.

### 5. Process a bid

**Via command line:**
```bash
source ~/ai-assistant/venv/bin/activate
python agent/bid_agent.py ~/Downloads/bid-package.pdf
```

**Via web interface:**
Type `process bid ~/Downloads/bid-package.pdf` in the chat.

**With AgentGuard (recommended):**
```bash
agentguard python ~/ai-assistant/agent/bid_agent.py ~/Downloads/bid.pdf
```

## Project Structure

```
ai-assistant/
├── install.sh              # macOS/Linux installer
├── install.ps1             # Windows installer
├── requirements.txt        # Python dependencies
├── security/
│   └── policy.yaml         # AgentGuard security policy
├── agent/
│   ├── __init__.py         # Package init
│   ├── bid_agent.py        # Main bid processing agent
│   ├── computer_control.py # Mouse/keyboard/Adobe automation
│   └── web_access.py       # Web browsing and email
├── config/
│   └── nanobot.json        # nanobot + MCP configuration
├── scripts/
│   ├── run.sh              # Start all services (macOS/Linux)
│   ├── run.ps1             # Start all services (Windows)
│   └── agentguard.sh       # AgentGuard command interceptor
├── logs/                   # All logs (auto-created)
├── models/                 # Local model cache
├── mcp/                    # Custom MCP servers
└── samples/                # Sample bid PDFs for testing
```

## How It Works

### Bid Processing Workflow

1. **PDF Parsing** — `bid_agent.py` reads the bid PDF using PyPDF2
2. **LLM Extraction** — The text is sent to Ollama/Mistral to extract structured data (line items, quantities, labor hours, deadlines)
3. **Price Estimation** — Each line item gets a unit price via keyword matching or LLM estimation
4. **Quote Calculation** — Material cost + labor + markup (25%) + tax (8.5%)
5. **Output** — Quote saved as JSON and Markdown to `~/Documents/Bids/`

### Adobe Automation

The `computer_control.py` module uses `pyautogui` to:
- Open Photoshop/Illustrator
- Create new documents
- Add text annotations and callouts
- Draw lines and arrows for bid markup
- Save completed drawings

### Web Access

The `web_access.py` module provides:
- DuckDuckGo search (no API key needed)
- Material price lookups
- Bid opportunity search
- Email composition (via Gmail/Outlook web)
- File downloads from allowed domains

### Security (AgentGuard)

Every command the AI tries to run passes through AgentGuard:

| Tier | Action | Example |
|------|--------|---------|
| **DENY** | Blocked immediately | `rm -rf /`, `sudo`, reading `~/.ssh` |
| **ALLOW** | Executed without prompt | `python`, `ollama`, `ls`, `cat` |
| **PROMPT** | Asks user for approval | Sending email, unknown commands |

All actions are logged to `~/ai-assistant/logs/agentguard.log`.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `mistral:7b` | Ollama model to use |
| `MARKUP_PERCENT` | `25` | Markup percentage for quotes |
| `TAX_PERCENT` | `8.5` | Tax percentage |
| `DEFAULT_LABOR_RATE` | `75` | Default labor rate ($/hr) |
| `BID_WORKSPACE` | `~/Documents/Bids` | Directory for bid files |
| `AI_ASSISTANT_LOG_DIR` | `~/ai-assistant/logs` | Log directory |
| `ALLOWED_DOMAINS` | *(see web_access.py)* | Extra allowed web domains (comma-separated) |
| `WEB_TIMEOUT` | `30` | HTTP request timeout in seconds |

### Switching Models

To use a smaller model (less RAM):
```bash
# In config/nanobot.json, change llm.model to:
"model": "llama3.2:3b"

# Pull the model
ollama pull llama3.2:3b

# Or set via environment variable
export OLLAMA_MODEL=llama3.2:3b
```

### Custom Pricing

Edit the `price_map` dictionary in `agent/bid_agent.py` to add or modify material prices for your region/industry.

## Troubleshooting

### Ollama won't start
```bash
# Check if port 11434 is in use
lsof -i :11434

# Restart Ollama
killall ollama
ollama serve
```

### Model download is slow
```bash
# Use a smaller model
ollama pull llama3.2:3b
```

### pyautogui fails on Linux
```bash
# Install X11 dependencies
sudo apt-get install python3-tk python3-dev scrot
```

### "No text extracted from PDF"
The PDF may be scanned (image-based). Install OCR support:
```bash
pip install pytesseract
sudo apt-get install tesseract-ocr  # Linux
brew install tesseract               # macOS
```

### Web search returns no results
DuckDuckGo may rate-limit requests. Wait a few seconds and retry, or check your network connection.

### nanobot not found
```bash
# Install via Go
go install github.com/nano-bot/nanobot@latest

# Or use the fallback web interface (starts automatically)
```

## Security Notes

- The AI **cannot** access `~/.ssh`, `~/.aws`, `.env` files, or private keys
- The AI **cannot** run `sudo`, `rm -rf /`, or `chmod 777`
- The AI **must** get your approval before sending emails or browsing unknown sites
- All actions are logged with timestamps to `~/ai-assistant/logs/`
- Network access is restricted to an explicit allowlist of domains
- The web interface only listens on `127.0.0.1` (localhost only)

## License

MIT License. See [LICENSE](LICENSE) for details.
