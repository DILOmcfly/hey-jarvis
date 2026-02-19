# 🎙 Hey Jarvis

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![OpenClaw](https://img.shields.io/badge/Powered%20by-OpenClaw-purple.svg)](https://github.com/openclaw/openclaw)
[![Release](https://img.shields.io/github/v/release/DILOmcfly/hey-jarvis)](https://github.com/DILOmcfly/hey-jarvis/releases)

**Open-source voice assistant with bidirectional speech.**  
Speak → AI processes → hear the response through your speakers. All running locally on your PC.

```
 "Hey Jarvis, what's the weather?"
         │
         ▼
   ┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────┐
   │  Wake Word   │ ──▶ │  Whisper GPU  │ ──▶ │   AI Agent   │ ──▶ │  Edge TTS   │
   │  Detection   │     │  Transcribe  │     │  (OpenClaw)  │     │  Voice Out  │
   └─────────────┘     └──────────────┘     └──────────────┘     └─────────────┘
         2s                  2s                   5s                   1.5s
                                                                        │
                                                                        ▼
                                                                   🔊 Speakers
```

> **Total latency: ~10-15 seconds** from speech to hearing the AI response.

---

## ✨ Features

- 🗣 **Wake word activation** — Say "Hey Jarvis" to activate (hands-free, always listening)
- 🧠 **Local speech-to-text** — Whisper large-v3 on your GPU (~2s transcription)
- 🤖 **AI-powered responses** — Powered by [OpenClaw](https://github.com/openclaw/openclaw) + Claude
- 🔊 **Voice responses** — Microsoft Edge TTS with natural Spanish voices (~1.5s generation)
- 💬 **Conversation mode** — 10-second window for follow-up commands without wake word
- 🎵 **Audio feedback** — Ding/done/error sounds for clear interaction feedback
- 🛡 **Hallucination filter** — Catches Whisper artifacts on silent/short audio
- 📊 **Health monitoring** — JSON stats, log rotation, auto-cleanup
- 🔄 **Auto-start** — Runs on boot (Windows Startup + systemd)
- 🌐 **Zero network config** — Windows ↔ WSL2 via shared folders

---

## 🏗 Architecture

Hey Jarvis runs as **4 lightweight services** across Windows and WSL2:

```
┌────────────────────────── WINDOWS ──────────────────────────┐
│                                                              │
│  🎙 hey_jarvis.py (Listener)     🔊 audio_player.py        │
│  ├─ openwakeword (wake word)     ├─ Watches response folder │
│  ├─ Silero VAD (voice detect)    ├─ Plays MP3 via speakers  │
│  ├─ Pre-buffer 0.5s              └─ Auto-moves to played/   │
│  ├─ Conversation mode 10s                                    │
│  └─ Saves WAV to shared folder         ▲ MP3                │
│         │ WAV                           │                    │
├─────────┼───────── Shared Folders ──────┼────────────────────┤
│         ▼                               │                    │
│  🔍 voice_watcher.py (Watcher)   📢 tts_speak.py (TTS)     │
│  ├─ faster-whisper large-v3 GPU  ├─ Edge TTS (Microsoft)    │
│  ├─ Transcription (~2s)          ├─ Voice: AlvaroNeural     │
│  ├─ Hallucination filter         └─ Generates MP3 (~1.5s)   │
│  ├─ Gateway API → OpenClaw                ▲                  │
│  └─ Polls for AI response ───────────────┘                  │
│                                                              │
└─────────────────────── WSL2 (Ubuntu) ───────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  OpenClaw/Claude  │
                    │  (AI Processing) │
                    └──────────────────┘
```

| Service | Runs on | Purpose |
|---------|---------|---------|
| `hey_jarvis.py` | Windows | Wake word detection + audio recording |
| `audio_player.py` | Windows | Auto-plays TTS responses through speakers |
| `voice_watcher.py` | WSL2 (systemd) | Whisper transcription + Gateway API + response polling |
| `tts_speak.py` | WSL2 | Edge TTS voice generation (called by watcher) |

---

## 💬 Real Example

Here's what a real interaction looks like:

```
👤 You:    "Hey Jarvis"
🔔 System: *ding* (listening...)

👤 You:    "What time is it in Tokyo right now?"
🔔 System: *done* (processing...)

  ⚡ Whisper transcribes in 1.8s
  ⚡ OpenClaw processes in 4.2s
  ⚡ Edge TTS generates voice in 1.3s

🔊 Speakers: "It's currently 9:43 AM in Tokyo, Wednesday morning."

👤 You:    "Play some lo-fi music on YouTube"
  (no wake word needed — conversation mode active for 10s)

🔊 Speakers: "Opening lo-fi music on YouTube for you."
  ⚡ Browser opens YouTube and plays music
```

The AI can do anything OpenClaw supports: search the web, control your browser, read files, run commands, check your calendar, and more — all by voice.

---

## 🚀 Quick Start

### Prerequisites

- **Windows 10/11** with [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) (Ubuntu 22.04+)
- **NVIDIA GPU** with CUDA support (RTX 3060+ recommended)
- **[OpenClaw](https://github.com/openclaw/openclaw)** installed and configured
- **Microphone** + **speakers/headphones**
- **Internet** connection (for Edge TTS + OpenClaw)

### WSL2 Configuration

Add to `C:\Users\<you>\.wslconfig`:
```ini
[wsl2]
networkingMode=mirrored
firewall=false
memory=16GB
```
> ⚠️ `firewall=false` is required for WSL2 ↔ Windows localhost communication.

Then restart WSL2: `wsl --shutdown` from PowerShell.

### 1. Clone the repo

```bash
# In WSL2
git clone https://github.com/DILOmcfly/hey-jarvis.git
cd hey-jarvis
```

### 2. Quick install (WSL2)

```bash
# Automated setup — configures venv, dependencies, and systemd
./install.sh
```

Or do it manually:

### 2b. Manual Setup WSL2 (Watcher + TTS)

```bash
# Create Whisper venv with GPU support
python3 -m venv ~/.venv-whisper
source ~/.venv-whisper/bin/activate
pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12 requests edge-tts

# Verify GPU
python3 -c "from faster_whisper import WhisperModel; m=WhisperModel('large-v3', device='cuda', compute_type='float16'); print('✅ Whisper GPU ready')"

# Verify Edge TTS
edge-tts --voice es-ES-AlvaroNeural --text "Hello" --write-media /tmp/test.mp3 && echo "✅ TTS ready"
```

### 3. Setup Windows (Listener + Player)

```powershell
# In Windows PowerShell
cd C:\path\to\hey-jarvis\listener
python -m venv venv
venv\Scripts\activate
pip install pyaudio openwakeword torch torchaudio onnxruntime
```

> 💡 If `pyaudio` fails: `pip install pipwin && pipwin install pyaudio`

### 4. Configure

```bash
# Copy and edit the config
cp listener/config.env.example listener/config.env
# Edit with your audio directory path

# Copy and edit the systemd service
cp watcher/voice-watcher.service ~/.config/systemd/user/
# Edit the service file with your paths and Gateway token
```

### 5. Create shared folders

```powershell
# In Windows
mkdir C:\Users\<you>\hey-jarvis-audio
mkdir C:\Users\<you>\hey-jarvis-responses
```

### 6. Start everything

```bash
# WSL2: Start watcher
systemctl --user daemon-reload
systemctl --user enable --now voice-watcher.service

# Windows: Start listener + player
cd C:\path\to\hey-jarvis\listener
venv\Scripts\python.exe hey_jarvis.py
# In another terminal:
venv\Scripts\python.exe audio_player.py
```

### 7. Test it!

Say **"Hey Jarvis"** and ask a question. You should hear a ding, speak your question, hear a done sound, and then hear the AI response through your speakers!

---

## ⚙️ Configuration

### Listener (`config.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `HJ_AUDIO_DIR` | `~/hey-jarvis-audio` | Shared folder for audio files |
| `HJ_WAKE_WORD` | `hey_jarvis_v0.1` | Wake word model name |
| `HJ_THRESHOLD` | `0.5` | Wake word sensitivity (0.0-1.0) |
| `HJ_CONV_WINDOW` | `10` | Seconds for follow-up without wake word |

### Watcher (systemd environment)

| Variable | Description |
|----------|-------------|
| `OPENCLAW_GATEWAY_URL` | OpenClaw Gateway URL (default: `http://localhost:18789`) |
| `OPENCLAW_GATEWAY_TOKEN` | Gateway authentication token |
| `TTS_VOICE` | Edge TTS voice (default: `es-ES-AlvaroNeural`) |

### Available TTS Voices

```bash
# List all voices
edge-tts --list-voices

# Spanish (Spain)
es-ES-AlvaroNeural    # Male, friendly ✅ default
es-ES-ElviraNeural    # Female, friendly
es-ES-XimenaNeural    # Female, friendly

# English
en-US-GuyNeural       # Male
en-US-JennyNeural     # Female
en-GB-RyanNeural      # Male, British

# Many more available — run the list command above
```

---

## 🔧 Auto-start on Boot

### Windows (Startup folder)

1. Press `Win+R`, type `shell:startup`, press Enter
2. Create `HeyJarvis.vbs`:

```vbs
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\path\to\hey-jarvis\listener"
WshShell.Run "venv\Scripts\python.exe hey_jarvis.py", 0, False
WshShell.Run "venv\Scripts\python.exe audio_player.py", 0, False
```

### WSL2 (systemd)

```bash
systemctl --user enable voice-watcher.service
# Starts automatically with WSL2
```

---

## 🐛 Troubleshooting

### Wake word not detecting

- **Speak clearly**: "Hey Jarvis" (English pronunciation works best)
- **Check threshold**: Lower `HJ_THRESHOLD` to 0.3 for more sensitivity
- **Microphone**: Ensure Windows has the right default microphone

### Whisper transcribes garbage ("Gracias por ver el video")

This is a known Whisper hallucination on short/silent audio. The watcher has a built-in filter for common artifacts. If you see new ones, add them to the `hallucinations` list in `voice_watcher.py`.

### Audio player doesn't play / cuts off

- **Check the response folder** has MP3 files
- **Duration estimation**: The player estimates duration from file size. If audio cuts off, increase the safety margin in `audio_player.py`

### CUDA out of memory

```bash
# Check GPU usage
nvidia-smi
# Close other GPU-heavy apps, or use a smaller Whisper model:
# Change WHISPER_MODEL = "medium" in voice_watcher.py
```

### WSL2 can't reach Windows localhost

Ensure `.wslconfig` has:
```ini
[wsl2]
networkingMode=mirrored
firewall=false
```
Then `wsl --shutdown` and restart.

### openwakeword loads ALL models (false positives)

Make sure the listener uses:
```python
OWWModel(wakeword_models=["hey_jarvis_v0.1"], inference_framework="onnx")
```
**NOT** `OWWModel()` which loads all built-in models.

### PyAudio installation fails on Windows

```powershell
pip install pipwin
pipwin install pyaudio
```

---

## 🧩 Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Wake word | [openwakeword](https://github.com/dscripka/openwakeword) | Free, open-source, custom wake words |
| VAD | [Silero VAD](https://github.com/snakers4/silero-vad) | Accurate, lightweight, built into openwakeword |
| STT | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | GPU-accelerated Whisper, 4x faster than original |
| AI Agent | [OpenClaw](https://github.com/openclaw/openclaw) + Claude | Powerful AI with tool use, memory, automation |
| TTS | [Edge TTS](https://github.com/rany2/edge-tts) | Free Microsoft neural voices, fast, high quality |
| IPC | Shared folders (Windows ↔ WSL2) | Zero config, zero latency |

---

## 📁 Project Structure

```
hey-jarvis/
├── README.md
├── LICENSE
├── listener/                    # Windows components
│   ├── hey_jarvis.py           # Wake word listener
│   ├── audio_player.py         # TTS response player
│   ├── config.env.example      # Configuration template
│   ├── requirements.txt        # Python dependencies
│   ├── setup_windows.ps1       # Windows setup script
│   └── sounds/                 # Audio feedback files
│       ├── ding.wav            # Wake word detected
│       ├── done.wav            # Recording complete
│       └── error.wav           # Error occurred
├── watcher/                    # WSL2 components
│   ├── voice_watcher.py        # Transcription daemon
│   ├── tts_speak.py            # Edge TTS generator
│   └── voice-watcher.service   # systemd unit file
└── docs/                       # Documentation
    └── BUILD-GUIDE.md          # Detailed build guide
```

---

## 🗺 Roadmap

- [ ] 🎯 Custom wake word training (Spanish TTS voices)
- [ ] 🎬 Demo video with [Remotion](https://remotion.dev)
- [ ] 🐳 Docker setup for WSL2 components
- [ ] 🌍 Multi-language support
- [ ] ⚡ Streaming TTS (start playing before full generation)
- [ ] 🏠 Smart home integration
- [ ] 📱 Mobile companion app

---

## 📜 Version History

| Version | Date | Changes |
|---------|------|---------|
| **V3** | 2026-02-19 | Voice responses (Edge TTS), audio player, full bidirectional speech |
| **V2** | 2026-02-18 | Pre-buffer, conversation mode, hallucination filter, Gateway API direct |
| **V1** | 2026-02-18 | Initial version, wake word + Whisper + Telegram relay |

---

## 🤝 Contributing

Contributions welcome! This project was born from a real need — a voice interface for an AI assistant that actually works. If you have ideas, open an issue or PR.

---

## 📄 License

MIT License — see [LICENSE](LICENSE).

---

## 🙏 Credits

Built by **Diego** ([@DILOmcfly](https://github.com/DILOmcfly)) and **Ikigai** (AI assistant powered by [OpenClaw](https://github.com/openclaw/openclaw)).

Inspired by the desire to talk to AI like in the movies. 🎬
