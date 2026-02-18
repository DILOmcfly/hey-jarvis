"""
🔊 Hey Jarvis V3 — Audio Response Player (Windows)
====================================================
Watches the shared response folder for new audio files from Edge TTS
and plays them through the PC speakers using MediaPlayer (supports MP3/WAV).

Runs on Windows natively alongside the listener.
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

# ─── Configuration ───────────────────────────────────────────────────────

RESPONSE_DIR = Path(os.environ.get(
    "HJ_RESPONSE_DIR",
    os.path.join(os.path.expanduser("~"), "oye-ikigai-responses")
))
PLAYED_DIR = RESPONSE_DIR / "played"
POLL_INTERVAL = 0.5

# Logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("audio-player")
logger.setLevel(logging.INFO)

_fh = RotatingFileHandler(
    str(LOG_DIR / "audio_player.log"),
    maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_fh.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(_ch)


# ─── Audio Playback ─────────────────────────────────────────────────────

def play_audio(audio_path: Path):
    """Play audio file through default speakers using Windows MediaPlayer."""
    if sys.platform != "win32":
        logger.error("Audio player only works on Windows")
        return

    try:
        import clr  # pythonnet
    except ImportError:
        pass

    try:
        # Use PowerShell MediaPlayer for MP3/WAV support
        import subprocess
        abs_path = str(audio_path.resolve()).replace("'", "''")

        # Estimate duration from file size (~8KB/s for edge-tts mp3)
        size_kb = audio_path.stat().st_size / 1024
        estimated_duration = max(int(size_kb / 7) + 3, 5)

        ps_script = f"""
Add-Type -AssemblyName PresentationCore
$p = New-Object System.Windows.Media.MediaPlayer
$p.Open([uri]"{abs_path}")
Start-Sleep -Milliseconds 500
$p.Play()
Start-Sleep {estimated_duration}
$p.Close()
"""
        logger.info("🔊 Playing: %s (~%ds)", audio_path.name, estimated_duration)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=estimated_duration + 10
        )
        if result.returncode == 0:
            logger.info("✅ Playback complete")
        else:
            logger.error("Playback error: %s", result.stderr[:200])

    except subprocess.TimeoutExpired:
        logger.warning("Playback timed out, moving on")
    except Exception as e:
        logger.error("Playback failed: %s", e)


def move_to_played(audio_path: Path, json_path: Path = None):
    """Move played files to played/ subfolder."""
    PLAYED_DIR.mkdir(exist_ok=True)
    try:
        audio_path.rename(PLAYED_DIR / audio_path.name)
        if json_path and json_path.exists():
            json_path.rename(PLAYED_DIR / json_path.name)
    except Exception as e:
        logger.warning("Could not move to played: %s", e)


# ─── Main Loop ──────────────────────────────────────────────────────────

def get_pending_responses() -> list:
    """Get response JSON files sorted by timestamp."""
    if not RESPONSE_DIR.exists():
        return []

    files = []
    now = time.time()
    for f in sorted(RESPONSE_DIR.glob("response_*.json")):
        try:
            if now - f.stat().st_mtime < 1.0:
                continue  # Wait for write to finish
            files.append(f)
        except OSError:
            continue
    return files


def main():
    logger.info("=" * 50)
    logger.info("🔊 Hey Jarvis V3 — Audio Response Player")
    logger.info("=" * 50)
    logger.info("Response dir: %s", RESPONSE_DIR)

    RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    PLAYED_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("👂 Watching for audio responses...")

    try:
        while True:
            for json_file in get_pending_responses():
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    audio_file = data.get("audio_file", "")
                    audio_path = RESPONSE_DIR / audio_file

                    if audio_path.exists():
                        play_audio(audio_path)
                        move_to_played(audio_path, json_file)
                    else:
                        logger.warning("Audio file not found: %s", audio_file)
                        json_file.unlink(missing_ok=True)

                except Exception as e:
                    logger.error("Error processing %s: %s", json_file.name, e)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("👋 Stopping audio player...")


if __name__ == "__main__":
    main()
