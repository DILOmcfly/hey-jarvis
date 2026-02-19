#!/bin/bash
# Hey Jarvis — Quick Setup Script (WSL2)
# Run this after cloning the repo to configure paths and services.

set -e

echo "🎙 Hey Jarvis — Setup"
echo "====================="
echo ""

# Detect user
USER_NAME=$(whoami)
WIN_USER=$(cmd.exe /C "echo %USERNAME%" 2>/dev/null | tr -d '\r' || echo "")

if [ -z "$WIN_USER" ]; then
    read -p "Windows username (e.g., diego): " WIN_USER
fi

echo "Linux user: $USER_NAME"
echo "Windows user: $WIN_USER"
echo ""

# ─── Paths ───────────────────────────────────────────────────────────────

AUDIO_DIR="/mnt/c/Users/$WIN_USER/hey-jarvis-audio"
RESPONSE_DIR="/mnt/c/Users/$WIN_USER/hey-jarvis-responses"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$HOME/.venv-whisper"

echo "📁 Creating shared folders..."
mkdir -p "$AUDIO_DIR" "$AUDIO_DIR/processed" "$AUDIO_DIR/failed"
mkdir -p "$RESPONSE_DIR" "$RESPONSE_DIR/played"
echo "   ✅ $AUDIO_DIR"
echo "   ✅ $RESPONSE_DIR"

# ─── Python venv ─────────────────────────────────────────────────────────

if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "🐍 Creating Python venv for Whisper..."
    python3 -m venv "$VENV_DIR"
fi

echo ""
echo "📦 Installing WSL2 dependencies..."
source "$VENV_DIR/bin/activate"
pip install -q -r "$REPO_DIR/watcher/requirements.txt"
echo "   ✅ Dependencies installed"

# ─── Verify GPU ──────────────────────────────────────────────────────────

echo ""
echo "🔍 Checking CUDA..."
python3 -c "
from faster_whisper import WhisperModel
m = WhisperModel('large-v3', device='cuda', compute_type='float16')
print('   ✅ Whisper GPU ready')
" 2>/dev/null || echo "   ⚠️  CUDA not available — Whisper will use CPU (slower)"

# ─── Gateway token ───────────────────────────────────────────────────────

echo ""
read -p "OpenClaw Gateway token (from openclaw.json): " GATEWAY_TOKEN

if [ -z "$GATEWAY_TOKEN" ]; then
    echo "⚠️  No token provided. You'll need to edit the service file manually."
    GATEWAY_TOKEN="YOUR_GATEWAY_TOKEN_HERE"
fi

# ─── Configure systemd service ──────────────────────────────────────────

echo ""
echo "⚙️  Configuring systemd service..."
mkdir -p "$HOME/.config/systemd/user"

WHISPER_CUBLAS=$(find "$VENV_DIR" -path "*/nvidia/cublas/lib" -type d 2>/dev/null | head -1)
WHISPER_CUDNN=$(find "$VENV_DIR" -path "*/nvidia/cudnn/lib" -type d 2>/dev/null | head -1)
LD_PATH="${WHISPER_CUBLAS}:${WHISPER_CUDNN}"

cat > "$HOME/.config/systemd/user/voice-watcher.service" << EOF
[Unit]
Description=Hey Jarvis - Voice Watcher Daemon
After=network.target

[Service]
Type=simple
ExecStart=$VENV_DIR/bin/python3 $REPO_DIR/watcher/voice_watcher.py
Restart=on-failure
RestartSec=10
Environment=OPENCLAW_GATEWAY_TOKEN=$GATEWAY_TOKEN
Environment=OPENCLAW_GATEWAY_URL=http://localhost:18789
Environment=LD_LIBRARY_PATH=$LD_PATH
WorkingDirectory=$REPO_DIR/watcher

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable voice-watcher.service
echo "   ✅ Service installed and enabled"

# ─── Summary ─────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════"
echo "✅ Setup complete!"
echo "════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo ""
echo "1. Setup Windows listener:"
echo "   cd /mnt/c/Users/$WIN_USER/Desktop"
echo "   cp -r $REPO_DIR/listener hey-jarvis-listener"
echo "   # Then in Windows PowerShell:"
echo "   # cd Desktop\\hey-jarvis-listener"
echo "   # python -m venv venv"
echo "   # venv\\Scripts\\activate"
echo "   # pip install -r requirements.txt"
echo ""
echo "2. Start the watcher:"
echo "   systemctl --user start voice-watcher.service"
echo ""
echo "3. Start the listener (Windows):"
echo "   venv\\Scripts\\python.exe hey_jarvis.py"
echo "   venv\\Scripts\\python.exe audio_player.py"
echo ""
echo "4. Say 'Hey Jarvis' and start talking! 🎙"
echo ""
