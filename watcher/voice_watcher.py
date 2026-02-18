#!/usr/bin/env python3
"""
🔍 Hey Jarvis V3 — Voice Watcher Daemon
=========================================
Monitors shared audio folder for WAV files from the Windows listener.
Transcribes with faster-whisper GPU and injects into OpenClaw via Gateway API.

Production-grade: logging, error handling, retry, health checks, file cleanup.
Runs as systemd user service in WSL2.
"""

import os
import sys
import json
import time
import wave
import signal
import logging
import asyncio
import re
import requests
from pathlib import Path
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

# ─── Configuration ───────────────────────────────────────────────────────

AUDIO_DIR = Path("/mnt/c/Users/YOUR_USER/hey-jarvis-audio")
PROCESSED_DIR = AUDIO_DIR / "processed"
FAILED_DIR = AUDIO_DIR / "failed"

GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://localhost:18789")
GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")

# Whisper config
WHISPER_MODEL = "large-v3"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE = "float16"
WHISPER_LANGUAGE = "es"

# Watcher config
POLL_INTERVAL = 0.5
MIN_FILE_AGE = 1.0
MIN_AUDIO_DURATION = 0.5
MAX_AUDIO_DURATION = 180  # 3 min max (V2 allows up to 2 min recording)
MAX_RETRIES = 3
RETRY_DELAY = 2
CLEANUP_DAYS = 7
HEALTH_INTERVAL = 60

# V3: Voice response config
TTS_VOICE = os.environ.get("TTS_VOICE", "es-ES-AlvaroNeural")
TTS_MAX_TEXT = 800
RESPONSE_DIR = Path("/mnt/c/Users/YOUR_USER/hey-jarvis-responses")
RESPONSE_POLL_INTERVAL = 2      # seconds between polls for OpenClaw response
RESPONSE_POLL_MAX_WAIT = 90     # max seconds to wait for response
RESPONSE_POLL_INITIAL_DELAY = 3 # initial delay before first poll

# Logging
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "voice_watcher_v3.log"

logger = logging.getLogger("voice-watcher-v3")
logger.setLevel(logging.INFO)

_fh = RotatingFileHandler(
    str(LOG_FILE), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_fh.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_fh)

if sys.stdout and hasattr(sys.stdout, 'write'):
    _ch = logging.StreamHandler()
    _ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    ))
    logger.addHandler(_ch)

# ─── Globals ─────────────────────────────────────────────────────────────

whisper_model = None
running = True
stats = {
    "started_at": None,
    "files_processed": 0,
    "files_failed": 0,
    "last_transcription": None,
    "last_error": None,
    "total_audio_seconds": 0,
    "total_transcription_seconds": 0,
}

# ─── Signal Handlers ────────────────────────────────────────────────────

def handle_signal(signum, frame):
    global running
    logger.info("Received signal %d, shutting down...", signum)
    running = False

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

# ─── Whisper ─────────────────────────────────────────────────────────────

def load_whisper():
    global whisper_model
    if whisper_model is not None:
        return whisper_model

    logger.info("Loading faster-whisper %s on %s (%s)...",
                WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE)

    from faster_whisper import WhisperModel
    whisper_model = WhisperModel(
        WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE
    )
    logger.info("Whisper model loaded ✅")
    return whisper_model


def transcribe(audio_path: Path) -> tuple[str, float]:
    """Transcribe audio file. Returns (text, duration_seconds)."""
    model = load_whisper()

    with wave.open(str(audio_path), 'rb') as wf:
        duration = wf.getnframes() / wf.getframerate()

    if duration < MIN_AUDIO_DURATION:
        raise ValueError(f"Audio too short: {duration:.1f}s")
    if duration > MAX_AUDIO_DURATION:
        raise ValueError(f"Audio too long: {duration:.1f}s")

    t0 = time.time()
    segments, info = model.transcribe(
        str(audio_path),
        language=WHISPER_LANGUAGE,
        beam_size=5,
        no_speech_threshold=0.6,
        condition_on_previous_text=False,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=300,
        ),
    )

    text = " ".join(seg.text.strip() for seg in segments).strip()
    elapsed = time.time() - t0

    logger.info("Transcribed %.1fs → %.1fs → '%s'", duration, elapsed, text[:120])

    stats["total_audio_seconds"] += duration
    stats["total_transcription_seconds"] += elapsed

    return text, duration

# ─── Gateway API ─────────────────────────────────────────────────────────

def send_to_openclaw(text: str, audio_file: str, duration: float) -> bool:
    """Inject transcribed voice command into OpenClaw session."""
    if not text.strip():
        logger.warning("Empty transcription, skipping")
        return False

    # Hallucination filter: common Whisper artifacts on silence
    hallucinations = [
        "gracias por ver el video", "suscríbete", "subtítulos",
        "gracias por ver", "hasta luego", "nos vemos",
    ]
    text_lower = text.lower().strip()
    if any(h in text_lower for h in hallucinations) and len(text_lower) < 40:
        logger.warning("Filtered hallucination: '%s'", text)
        return False

    message = (
        f"[Voice Command via Hey Jarvis] "
        f"Diego dijo por voz: \"{text}\"\n"
        f"(archivo: {audio_file}, duracion: {duration:.1f}s)"
    )

    headers = {
        "Authorization": f"Bearer {GATEWAY_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "tool": "cron",
        "args": {"action": "wake", "text": message, "mode": "now"},
        "sessionKey": "agent:main:main",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                f"{GATEWAY_URL}/tools/invoke",
                json=payload, headers=headers, timeout=15,
            )
            if resp.status_code == 200 and resp.json().get("ok"):
                logger.info("✅ Sent to OpenClaw (attempt %d)", attempt)
                return True
            else:
                logger.warning("Gateway response: %d %s", resp.status_code, resp.text[:200])
        except requests.exceptions.ConnectionError:
            logger.warning("Gateway unreachable (attempt %d/%d)", attempt, MAX_RETRIES)
        except Exception as e:
            logger.error("Gateway error (attempt %d/%d): %s", attempt, MAX_RETRIES, e)

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    stats["last_error"] = datetime.now().isoformat()
    return False

# ─── V3: Voice Response ──────────────────────────────────────────────────

def clean_text_for_speech(text: str) -> str:
    """Clean markdown/emoji from text for natural TTS."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'#{1,6}\s', '', text)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[\U0001F300-\U0001F9FF\U00002700-\U000027BF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF]', '', text)
    text = re.sub(r'^[\s]*[•\-\*]\s', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{2,}', '. ', text)
    text = re.sub(r'\n', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    text = text.strip()
    if len(text) > TTS_MAX_TEXT:
        truncated = text[:TTS_MAX_TEXT]
        last_period = truncated.rfind('.')
        if last_period > TTS_MAX_TEXT // 2:
            text = truncated[:last_period + 1]
        else:
            text = truncated + "..."
    return text


def generate_voice_response(text: str):
    """Generate speech with Edge TTS and save to shared folder."""
    try:
        import edge_tts
    except ImportError:
        logger.error("edge-tts not installed, skipping voice response")
        return

    clean = clean_text_for_speech(text)
    if not clean:
        logger.warning("Empty text after cleaning, skipping TTS")
        return

    RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_path = RESPONSE_DIR / f"response_{timestamp}.mp3"
    json_path = RESPONSE_DIR / f"response_{timestamp}.json"

    try:
        communicate = edge_tts.Communicate(clean, TTS_VOICE)
        asyncio.run(communicate.save(str(audio_path)))

        if audio_path.exists() and audio_path.stat().st_size > 0:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "audio_file": audio_path.name,
                    "text": clean[:200],
                    "voice": TTS_VOICE,
                    "timestamp": timestamp,
                }, f, ensure_ascii=False, indent=2)
            logger.info("🔊 Voice response saved: %s (%d bytes)",
                       audio_path.name, audio_path.stat().st_size)
        else:
            logger.error("TTS generated empty file")
    except Exception as e:
        logger.error("TTS error: %s", e)


def get_last_assistant_message() -> tuple:
    """Get the last assistant text message and its timestamp from OpenClaw."""
    headers = {
        "Authorization": f"Bearer {GATEWAY_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "tool": "sessions_history",
        "args": {"sessionKey": "agent:main:main", "limit": 3, "includeTools": False},
    }
    try:
        resp = requests.post(
            f"{GATEWAY_URL}/tools/invoke",
            json=payload, headers=headers, timeout=10,
        )
        if resp.status_code != 200:
            return None, 0

        data = resp.json()
        # Navigate the nested response
        result = data.get("result", {})
        details = result.get("details", result)
        messages = details.get("messages", [])

        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", [])
            if isinstance(content, str):
                return content, msg.get("timestamp", 0)
            # Extract text parts from content array
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            if text_parts:
                return " ".join(text_parts), msg.get("timestamp", 0)

    except Exception as e:
        logger.error("Error fetching assistant message: %s", e)

    return None, 0


def wait_and_speak_response(send_time: float):
    """Poll for OpenClaw's response and speak it via TTS."""
    logger.info("⏳ Waiting for OpenClaw response...")
    time.sleep(RESPONSE_POLL_INITIAL_DELAY)

    send_ts_ms = int(send_time * 1000)
    elapsed = RESPONSE_POLL_INITIAL_DELAY

    while elapsed < RESPONSE_POLL_MAX_WAIT:
        text, ts = get_last_assistant_message()

        if text and ts > send_ts_ms:
            # Filter out NO_REPLY and tool-only responses
            if text.strip() == "NO_REPLY" or not text.strip():
                logger.info("Response is NO_REPLY or empty, checking for Telegram message...")
                # The actual response might have been sent via message tool
                # Wait a bit more and check again
                time.sleep(3)
                elapsed += 3
                continue

            logger.info("📨 Got response (%d chars): '%s'", len(text), text[:80])
            generate_voice_response(text)
            return

        time.sleep(RESPONSE_POLL_INTERVAL)
        elapsed += RESPONSE_POLL_INTERVAL

    logger.warning("⏰ Timed out waiting for response after %ds", RESPONSE_POLL_MAX_WAIT)


# ─── File Processing ─────────────────────────────────────────────────────

def move_file(src: Path, dest_dir: Path):
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    try:
        src.rename(dest)
    except OSError:
        import shutil
        shutil.move(str(src), str(dest))


def process_file(audio_path: Path):
    logger.info("Processing: %s", audio_path.name)

    try:
        text, duration = transcribe(audio_path)

        if not text.strip():
            logger.warning("Empty transcription, moving to failed")
            move_file(audio_path, FAILED_DIR)
            stats["files_failed"] += 1
            return

        send_time = time.time()
        success = send_to_openclaw(text, audio_path.name, duration)

        if success:
            move_file(audio_path, PROCESSED_DIR)
            stats["files_processed"] += 1
            stats["last_transcription"] = {
                "file": audio_path.name,
                "text": text[:200],
                "duration": duration,
                "at": datetime.now().isoformat(),
            }
            # V3: Wait for response and speak it
            import threading
            t = threading.Thread(
                target=wait_and_speak_response,
                args=(send_time,),
                daemon=True,
            )
            t.start()
        else:
            logger.error("Failed to send to OpenClaw")
            move_file(audio_path, FAILED_DIR)
            stats["files_failed"] += 1

    except ValueError as e:
        logger.warning("Skipping %s: %s", audio_path.name, e)
        move_file(audio_path, FAILED_DIR)
        stats["files_failed"] += 1
    except Exception as e:
        logger.error("Error processing %s: %s", audio_path.name, e, exc_info=True)
        move_file(audio_path, FAILED_DIR)
        stats["files_failed"] += 1
        stats["last_error"] = str(e)

# ─── Cleanup & Health ────────────────────────────────────────────────────

def cleanup_old_files():
    cutoff = datetime.now() - timedelta(days=CLEANUP_DAYS)
    for d in [PROCESSED_DIR, FAILED_DIR]:
        if not d.exists():
            continue
        for f in d.glob("*.wav"):
            try:
                if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                    f.unlink()
                    logger.info("Cleaned: %s", f.name)
            except Exception:
                pass


def write_health():
    health_file = LOG_DIR / "voice_watcher_v3_health.json"
    health = {
        "status": "running",
        "version": "2.0",
        "pid": os.getpid(),
        "uptime_seconds": (
            (datetime.now() - datetime.fromisoformat(stats["started_at"])).total_seconds()
            if stats["started_at"] else 0
        ),
        "stats": stats,
        "checked_at": datetime.now().isoformat(),
    }
    try:
        with open(health_file, 'w') as f:
            json.dump(health, f, indent=2, default=str)
    except Exception:
        pass

# ─── Main ────────────────────────────────────────────────────────────────

def get_pending_files() -> list[Path]:
    if not AUDIO_DIR.exists():
        return []
    now = time.time()
    files = []
    for f in sorted(AUDIO_DIR.glob("ikigai_*.wav")):
        try:
            if now - f.stat().st_mtime >= MIN_FILE_AGE:
                files.append(f)
        except OSError:
            continue
    return files


def main():
    logger.info("=" * 60)
    logger.info("🔍 Hey Jarvis V3 — Voice Watcher Daemon")
    logger.info("=" * 60)
    logger.info("Audio dir:  %s", AUDIO_DIR)
    logger.info("Gateway:    %s", GATEWAY_URL)
    logger.info("Whisper:    %s (%s/%s)", WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE)

    if not GATEWAY_TOKEN:
        logger.error("OPENCLAW_GATEWAY_TOKEN not set!")
        sys.exit(1)

    for d in [AUDIO_DIR, PROCESSED_DIR, FAILED_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    stats["started_at"] = datetime.now().isoformat()
    last_health = 0
    last_cleanup = 0

    try:
        load_whisper()
    except Exception as e:
        logger.error("Failed to load Whisper: %s (will retry)", e)

    logger.info("👂 Watching for audio files...")

    while running:
        try:
            for audio_file in get_pending_files():
                if not running:
                    break
                process_file(audio_file)

            now = time.time()
            if now - last_health > HEALTH_INTERVAL:
                write_health()
                last_health = now
            if now - last_cleanup > 3600:
                cleanup_old_files()
                last_cleanup = now

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("Main loop error: %s", e, exc_info=True)
            time.sleep(5)

    logger.info("Shutdown. Stats: %s", json.dumps(stats, default=str))
    write_health()


if __name__ == "__main__":
    main()
