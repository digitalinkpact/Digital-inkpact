#!/usr/bin/env bash
set -euo pipefail

echo "=== Setting up Digital-inkpact environment ==="

# Install Ollama
if ! command -v ollama &>/dev/null; then
    echo "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

# Start Ollama in background
echo "Starting Ollama on port 11434..."
ollama serve &>/dev/null &
OLLAMA_PID=$!

# Wait for Ollama to be ready
for i in $(seq 1 30); do
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        echo "Ollama is ready on port 11434"
        break
    fi
    sleep 1
done

# Pull the model
echo "Pulling mistral:7b model (this may take a few minutes)..."
ollama pull mistral:7b || echo "Model pull failed - you can run 'ollama pull mistral:7b' later"

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r ai-assistant/requirements.txt

echo "=== Setup complete ==="
echo "  Ollama: http://localhost:11434"
echo "  Run 'bash ai-assistant/scripts/run.sh' to start the app"
