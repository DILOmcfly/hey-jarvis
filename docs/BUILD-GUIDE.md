# 🎙 Hey Jarvis V3 — Build Guide

> Fecha: 2026-02-19
> Autor: Ikigai (asistente de Diego)
> Versión: V3 (Voice In + Voice Out)

---

## 📋 Índice

1. [Qué es V3](#qué-es-v3)
2. [Arquitectura](#arquitectura)
3. [Componentes y modelos](#componentes-y-modelos)
4. [Requisitos previos](#requisitos-previos)
5. [Instalación paso a paso](#instalación-paso-a-paso)
6. [Configuración](#configuración)
7. [Auto-start](#auto-start)
8. [Testing](#testing)
9. [Errores conocidos y soluciones](#errores-conocidos-y-soluciones)
10. [Decisiones de diseño](#decisiones-de-diseño)
11. [Historial de cambios V2 → V3](#historial-de-cambios-v2--v3)
12. [Archivos clave](#archivos-clave)

---

## Qué es V3

Hey Jarvis V3 es un asistente de voz **bidireccional**: Diego habla → OpenClaw/Claude procesa → Ikigai responde por voz a través de los altavoces del PC.

**V3 = V2 (voice input) + Edge TTS (voice output)**

### Lo que cambió de V2 a V3
- **NUEVO**: Respuesta por voz via Edge TTS (Microsoft, voz "Álvaro")
- **NUEVO**: Audio player en Windows que reproduce respuestas automáticamente
- **NUEVO**: Script `tts_speak.py` que OpenClaw ejecuta para hablar
- **DESCARTADO**: Orpheus TTS local (calidad insuficiente en español, 14s vs 1.5s de Edge TTS)
- Todo lo demás de V2 se mantiene intacto

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────────┐
│                        WINDOWS (Nativo)                            │
│                                                                     │
│  hey_jarvis.py (Listener)          audio_player.py (Player)        │
│  ├─ openwakeword "Hey Jarvis"      ├─ Vigila hey-jarvis-responses/ │
│  ├─ Silero VAD (detección voz)     ├─ Reproduce MP3 automáticamente│
│  ├─ Pre-buffer 0.5s                └─ Mueve a played/ después      │
│  ├─ Conversation mode 10s                                          │
│  ├─ 3 sonidos (ding/done/error)                                    │
│  └─ Guarda WAV en carpeta compartida                               │
│         │                                    ▲                      │
│         │ WAV                                │ MP3                  │
│         ▼                                    │                      │
├─────── /mnt/c/Users/<your-user>/ ─────────────────────────────────────────┤
│         hey-jarvis-audio/              hey-jarvis-responses/        │
│                                                                     │
│                        WSL2 (Ubuntu)                                │
│                                                                     │
│  voice_watcher.py (Watcher)          tts_speak.py (TTS)            │
│  ├─ faster-whisper large-v3 GPU      ├─ Edge TTS (Microsoft)       │
│  ├─ Transcribe WAV → texto           ├─ Voz: es-ES-AlvaroNeural   │
│  ├─ Filtro alucinaciones Whisper     ├─ Genera MP3 en ~1.5s        │
│  ├─ Gateway API → OpenClaw           └─ Guarda en carpeta compartida│
│  └─ Health monitoring                                               │
│         │                                    ▲                      │
│         │ wake event                         │ exec tts_speak.py   │
│         ▼                                    │                      │
│  ┌──────────────────────────────────────────────┐                   │
│  │            OpenClaw / Claude                  │                   │
│  │  ├─ Recibe [Voice Command via Hey Jarvis]     │                   │
│  │  ├─ Procesa el comando                        │                   │
│  │  ├─ Responde por Telegram                     │                   │
│  │  └─ Ejecuta tts_speak.py → audio → altavoces │                   │
│  └──────────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Componentes y modelos

### Modelos de IA

| Componente | Modelo | Detalle |
|------------|--------|---------|
| **Wake word** | `hey_jarvis_v0.1` | Built-in de openwakeword. Entrenado en inglés pero funciona con acento español |
| **VAD** | Silero VAD v5 | Detección de actividad de voz, integrado en openwakeword |
| **STT (Speech-to-Text)** | `faster-whisper large-v3` | OpenAI Whisper, ejecución CUDA/float16. ~1-2s para 15s de audio |
| **LLM** | Claude (Anthropic) | Via OpenClaw Gateway API. Modelo configurable en openclaw.json |
| **TTS (Text-to-Speech)** | Microsoft Edge TTS | Voz `es-ES-AlvaroNeural`. Gratis, ~1.5s generación, calidad profesional |

### Voces Edge TTS disponibles (español España)

| Voz | Género | Estilo |
|-----|--------|--------|
| `es-ES-AlvaroNeural` | Masculina | Amigable, positivo ✅ **ELEGIDA** |
| `es-ES-ElviraNeural` | Femenina | Amigable, positivo |
| `es-ES-XimenaNeural` | Femenina | Amigable, positivo |

Para cambiar de voz: editar variable `TTS_VOICE` en `tts_speak.py` o pasar `--voice`.

### Modelos descartados

| Modelo | Razón del descarte |
|--------|-------------------|
| **Orpheus TTS 3B** (local, GGUF) | Calidad muy baja en español ("viejo drogado"), 14s/frase en GPU vs 1.5s Edge TTS |
| **Piper TTS** | Rápido pero robótico, voces españolas limitadas |
| **Custom "oye_ikigai" wake word** | Entrenado con TTS inglés, no reconoce habla española real |

---

## Requisitos previos

### Hardware
- **PC**: Windows 10/11 con WSL2
- **GPU**: NVIDIA con CUDA (RTX 4070 o superior recomendado)
- **Micrófono**: Cualquiera (USB, integrado, cascos)
- **Audio output**: Altavoces o cascos conectados a Windows
- **Internet**: Requerido (Edge TTS + OpenClaw)

### Software (Windows)
- Python 3.10+ (python.exe en PATH)
- PowerShell 5.1+
- WSL2 con Ubuntu 22.04/24.04

### Software (WSL2)
- Python 3.12
- NVIDIA CUDA drivers (nvidia-smi debe funcionar)
- faster-whisper con CUDA (`pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12`)
- edge-tts (`pip install edge-tts`)
- OpenClaw instalado y configurado

### Configuración WSL2
En `C:\Users\<user>\.wslconfig`:
```ini
[wsl2]
networkingMode=mirrored
firewall=false
memory=16GB
```
> **CRÍTICO**: `firewall=false` es necesario para que WSL2 acceda a Windows localhost (MCP, CDP).

---

## Instalación paso a paso

### 1. Estructura de carpetas

```
# Windows
C:\Users\<your-user>\Desktop\hey-jarvis\          # Listener + Player
C:\Users\<your-user>\hey-jarvis-audio\               # Audio input (WAVs del listener)
C:\Users\<your-user>\hey-jarvis-audio\processed\     # WAVs procesados
C:\Users\<your-user>\hey-jarvis-audio\failed\        # WAVs fallidos
C:\Users\<your-user>\hey-jarvis-responses\           # Audio output (MP3s del TTS)
C:\Users\<your-user>\hey-jarvis-responses\played\    # MP3s reproducidos

# WSL2
~/.openclaw/workspace/projects/hey-jarvis/  # Source code
~/.openclaw/workspace/scripts/speak.sh          # Wrapper TTS
~/.openclaw/workspace/logs/                     # Logs del watcher
```

### 2. Instalar listener (Windows)

```powershell
cd C:\Users\<your-user>\Desktop\hey-jarvis
python -m venv venv
venv\Scripts\activate
pip install pyaudio openwakeword torch torchaudio onnxruntime
```

> **Si pyaudio falla**: `pip install pipwin && pipwin install pyaudio`

### 3. Instalar watcher (WSL2)

```bash
# Crear venv de Whisper (si no existe)
python3 -m venv ~/.venv-whisper
source ~/.venv-whisper/bin/activate
pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12 requests

# Edge TTS (puede ir en system o venv)
pip install --user edge-tts --break-system-packages
```

### 4. Configurar listener

Editar `C:\Users\<your-user>\Desktop\hey-jarvis\config.env`:
```ini
# Carpeta de audio (compartida con WSL2)
HJ_AUDIO_DIR=C:\Users\<your-user>\hey-jarvis-audio

# Wake word
HJ_WAKE_WORD=hey_jarvis_v0.1
HJ_THRESHOLD=0.5

# Conversation mode (segundos para segundo comando sin wake word)
HJ_CONV_WINDOW=10
```

### 5. Instalar systemd service (WSL2)

```bash
cp projects/hey-jarvis/watcher/voice-watcher-v3.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable voice-watcher-v3.service
systemctl --user start voice-watcher-v3.service
```

### 6. Verificar

```bash
# Watcher corriendo?
systemctl --user status voice-watcher-v3.service

# Whisper GPU?
python3 -c "from faster_whisper import WhisperModel; m=WhisperModel('large-v3', device='cuda', compute_type='float16'); print('OK')"

# Edge TTS?
edge-tts --voice es-ES-AlvaroNeural --text "Test" --write-media /tmp/test.mp3 && echo OK

# Gateway?
curl -s http://localhost:18789/health
```

---

## Configuración

### Variables de entorno del watcher (`voice-watcher-v3.service`)

| Variable | Valor | Descripción |
|----------|-------|-------------|
| `OPENCLAW_GATEWAY_TOKEN` | `YOUR_GATEWAY_TOKEN...` | Token de autenticación Gateway |
| `OPENCLAW_GATEWAY_URL` | `http://localhost:18789` | URL del Gateway |
| `LD_LIBRARY_PATH` | `/home/<your-user>/.venv-whisper/...` | Paths a CUDA libs |

### Variables de entorno TTS (`tts_speak.py`)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `TTS_VOICE` | `es-ES-AlvaroNeural` | Voz de Edge TTS |

### Parámetros del listener (`hey_jarvis.py`)

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| Wake word model | `hey_jarvis_v0.1` | Solo este modelo, no cargar built-ins |
| Inference framework | `onnx` | Más fiable que tflite en Windows |
| Threshold | 0.5 | Sensibilidad del wake word |
| Pre-buffer | 0.5s | Audio antes del wake word que se incluye |
| Conversation window | 10s | Tiempo para segundo comando sin wake word |
| Max recording | 120s | Máximo de grabación continua |
| Abort silence | 5s | Aborta si no hay voz en 5s |

---

## Auto-start

### Windows (Startup folder)

Archivo: `HeyJarvisV3.vbs` en `shell:startup`

```vbs
' Lanza listener + audio_player ocultos
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\<your-user>\Desktop\hey-jarvis"
WshShell.Run "venv\Scripts\python.exe hey_jarvis.py", 0, False
WshShell.Run "venv\Scripts\python.exe audio_player.py", 0, False
```

### WSL2 (systemd)

```bash
systemctl --user enable voice-watcher-v3.service
# Se inicia automáticamente con WSL2
```

### Servicios totales al arranque (3)

1. `HeyJarvisV3.vbs` → listener + audio_player (Windows)
2. `voice-watcher-v3.service` → watcher + Whisper GPU (WSL2)
3. `Brave CDP.bat` → Browser control (Windows, ya existente)

---

## Testing

### Test 1: Wake word
1. Ejecutar `hey_jarvis.py` manualmente
2. Decir "Hey Jarvis"
3. Debe sonar "ding" y empezar a grabar
4. Hablar algo → debe sonar "done" al terminar

### Test 2: Transcripción
1. Verificar que aparece WAV en `hey-jarvis-audio/`
2. Verificar logs: `journalctl --user -u voice-watcher-v3 -f`
3. El WAV debe moverse a `processed/`

### Test 3: Respuesta por voz
```bash
python3 projects/hey-jarvis/watcher/tts_speak.py "Esto es una prueba de voz"
```
Debe:
- Generar MP3 en `hey-jarvis-responses/`
- El audio_player lo reproduce por altavoces
- Se mueve a `played/`

### Test 4: End-to-end
1. Decir "Hey Jarvis, ¿qué hora es?"
2. Esperar transcripción (~2s)
3. OpenClaw procesa (~3s)
4. Respuesta por voz (~1.5s generación + reproducción)
5. Total esperado: ~10-15 segundos

---

## Errores conocidos y soluciones

### ❌ Error: `PortAudio library not found`
**Dónde**: Al instalar pyaudio en Windows
**Solución**: `pip install pipwin && pipwin install pyaudio`
**Alternativa**: Descargar wheel de https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio

### ❌ Error: `OSError: PortAudio library not found` (Orpheus en WSL2)
**Dónde**: Al importar sounddevice en WSL2
**Solución**: Parchear import como opcional:
```python
try:
    import sounddevice as sd
except (OSError, ImportError):
    sd = None
```

### ❌ Error: openwakeword carga TODOS los wake words built-in
**Síntoma**: "weather" se activa con score 0.922 cuando dices cualquier cosa
**Causa**: `OWWModel()` sin params carga alexa, weather, hey_jarvis, etc.
**Solución**: `OWWModel(wakeword_models=["hey_jarvis_v0.1"], inference_framework="onnx")`

### ❌ Error: Whisper genera "Gracias por ver el video"
**Síntoma**: Comandos vacíos/cortos se transcriben como frases de YouTube
**Causa**: Alucinaciones de Whisper en audio corto/silencioso
**Solución**: Filtro de alucinaciones en watcher (lista de frases conocidas + umbral 40 chars)

### ❌ Error: Proceso zombie tras desactivar auto-start
**Síntoma**: V1/V2 sigue procesando audio aunque desactivaste el VBS/service
**Causa**: Desactivar auto-start solo previene futuros arranques, no mata procesos activos
**Solución**: SIEMPRE `kill` procesos ANTES de desactivar auto-start
**Comando**: `taskkill /F /IM python.exe /FI "WINDOWTITLE eq *hey_jarvis*"` o buscar PIDs

### ❌ Error: Audio se corta antes de terminar
**Síntoma**: La reproducción por altavoces se interrumpe a mitad de frase
**Causa**: `Start-Sleep` demasiado corto para la duración del audio
**Solución**: El audio_player calcula duración estimada del audio (`tamaño_KB / 7 + 3s`)

### ❌ Error: `dpkg lock` al instalar paquetes con apt
**Síntoma**: `E: Could not get lock /var/lib/dpkg/lock-frontend`
**Causa**: Otro apt-get corriendo (o zombie de proceso anterior cortado)
**Solución**:
```bash
sudo kill -9 $(lsof /var/lib/dpkg/lock-frontend 2>/dev/null | awk 'NR>1{print $2}')
sudo rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock
sudo dpkg --configure -a
```

### ❌ Error: `device token mismatch` en OpenClaw
**Síntoma**: Todas las herramientas RPC dejan de funcionar
**Causa**: Cambio en `allowInsecureAuth` o borrado de `device.json`
**Solución**: Ver `/mnt/c/Users/<your-user>/Documents/INCIDENTE-DEVICE-TOKEN-MISMATCH.md`
**REGLA**: NUNCA cambiar `allowInsecureAuth` a `false`

### ❌ Error: Edge TTS falla silenciosamente
**Síntoma**: No se genera audio, sin error claro
**Causa**: Sin conexión a internet o Microsoft bloqueó temporalmente
**Solución**: Verificar internet, reintentar. Edge TTS es muy estable pero depende de red.

### ❌ Error: CUDA out of memory
**Síntoma**: Whisper falla al cargar modelo
**Causa**: GPU VRAM ocupada por otro proceso
**Solución**: `nvidia-smi` para ver uso, cerrar aplicaciones que usen GPU

### ⚠️ Advertencia: WSL2 firewall bloquea localhost
**Síntoma**: WSL2 no puede conectar a Windows (MCP, CDP, etc.)
**Causa**: Hyper-V firewall activo
**Solución**: `.wslconfig` con `firewall=false` y `networkingMode=mirrored`

---

## Decisiones de diseño

### ¿Por qué Edge TTS y no Orpheus/Piper/XTTS?

| Criterio | Edge TTS | Orpheus 3B | Piper | XTTS v2 |
|----------|----------|------------|-------|---------|
| Calidad español | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| Velocidad | ~1.5s | ~14s GPU | ~0.5s | ~8s GPU |
| Recursos | 0 (cloud) | 4GB VRAM | 0.1GB | 4GB VRAM |
| Offline | ❌ | ✅ | ✅ | ✅ |
| Coste | Gratis | Gratis | Gratis | Gratis |

**Conclusión**: Edge TTS gana en calidad y velocidad. No necesitamos offline porque OpenClaw requiere internet.

### ¿Por qué carpetas compartidas y no red?
- WSL2 tiene acceso directo a `/mnt/c/` sin configuración
- Zero latencia de red
- No hay puertos que configurar
- Funciona siempre

### ¿Por qué systemd y no script manual?
- Auto-restart en caso de crash
- Auto-start con WSL2
- Logs via `journalctl`
- Gestión estándar (`start/stop/status`)

### ¿Por qué listener en Windows y no WSL2?
- WSL2 NO tiene acceso al micrófono
- Windows tiene acceso directo a audio hardware
- openwakeword funciona bien en Windows con ONNX

---

## Historial de cambios V2 → V3

| # | Cambio | Detalle |
|---|--------|---------|
| 1 | ➕ Edge TTS | `tts_speak.py` — generación de voz con Microsoft |
| 2 | ➕ Audio Player | `audio_player.py` — reproducción automática en Windows |
| 3 | ➕ speak.sh | Wrapper para ejecutar TTS desde OpenClaw |
| 4 | 🔄 VBS actualizado | Lanza listener + audio_player (antes solo listener) |
| 5 | 🗑 Orpheus descartado | Calidad insuficiente, demasiado lento |
| 6 | 📝 Watcher renombrado | v2 → v3 en logs y service |

---

## Archivos clave

### Source (WSL2)
```
projects/hey-jarvis/
├── README.md                          # Resumen del proyecto
├── docs/
│   └── V3-BUILD-GUIDE.md             # Este documento
├── listener/
│   ├── hey_jarvis.py                  # Wake word listener (Windows)
│   ├── audio_player.py                # Reproductor de respuestas (Windows)
│   ├── config.env                     # Configuración listener
│   ├── requirements.txt               # Dependencias Python Windows
│   ├── setup_windows.ps1              # Script de setup Windows
│   ├── start_v3.bat                   # Arranque manual
│   ├── start_silent_v3.vbs            # Arranque silencioso (auto-start)
│   └── sounds/                        # ding.wav, done.wav, error.wav
├── watcher/
│   ├── voice_watcher.py               # Daemon de transcripción (WSL2)
│   ├── tts_speak.py                   # Generador de voz Edge TTS
│   └── voice-watcher-v3.service       # Systemd unit file
└── tts-server/                        # Orpheus (DESCARTADO, conservado como referencia)
```

### Deployed (Windows)
```
C:\Users\<your-user>\Desktop\hey-jarvis\
├── hey_jarvis.py
├── audio_player.py
├── config.env
├── start_v3.bat
├── start_silent_v3.vbs
├── sounds\
├── logs\
└── venv\
```

### Logs
```
~/.openclaw/workspace/logs/voice_watcher_v3.log       # Watcher
~/.openclaw/workspace/logs/voice_watcher_v3_health.json # Health stats
C:\Users\<your-user>\Desktop\hey-jarvis\logs\             # Listener + Player
```

### Backups
```
backups/hey-jarvis_20260219_003156.tar.gz    # V3 completo
backups/hey-jarvis-v2_20260218_224753.tar.gz    # V2 (referencia)
backups/oye-ikigai-full_20260218_220451.tar.gz  # V1 (histórico)
```
