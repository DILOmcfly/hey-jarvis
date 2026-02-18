#!/usr/bin/env python3
"""
🔊 Hey Jarvis V3 — TTS Speak Utility (Edge TTS)
==================================================
Generates speech using Microsoft Edge TTS (free, fast, high quality).
Saves WAV to shared folder for Windows playback.

Usage:
    python3 tts_speak.py "Hola Diego"
    python3 tts_speak.py --voice es-ES-ElviraNeural "Texto"
"""

import os
import sys
import re
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime

import edge_tts

# ─── Configuration ───────────────────────────────────────────────────────

DEFAULT_VOICE = os.environ.get("TTS_VOICE", "es-ES-AlvaroNeural")
RESPONSE_DIR = Path("/mnt/c/Users/YOUR_USER/hey-jarvis-responses")
MAX_TEXT_LENGTH = 800


# ─── Text Cleaning ──────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Clean text for natural speech."""
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

    if len(text) > MAX_TEXT_LENGTH:
        truncated = text[:MAX_TEXT_LENGTH]
        last_period = truncated.rfind('.')
        if last_period > MAX_TEXT_LENGTH // 2:
            text = truncated[:last_period + 1]
        else:
            text = truncated + "..."

    return text


# ─── TTS ─────────────────────────────────────────────────────────────────

async def generate_speech(text: str, voice: str, output_path: Path) -> bool:
    """Generate speech with Edge TTS."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_path))
    return output_path.exists() and output_path.stat().st_size > 0


def speak(text: str, voice: str = None) -> bool:
    """Generate speech and save to shared folder."""
    voice = voice or DEFAULT_VOICE
    clean = clean_text(text)

    if not clean:
        print("Empty text after cleaning", file=sys.stderr)
        return False

    print(f"TTS: voice={voice}, text='{clean[:60]}...'")

    RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    wav_path = RESPONSE_DIR / f"response_{timestamp}.mp3"
    json_path = RESPONSE_DIR / f"response_{timestamp}.json"

    try:
        success = asyncio.run(generate_speech(clean, voice, wav_path))

        if success:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "audio_file": wav_path.name,
                    "text": clean[:200],
                    "voice": voice,
                    "timestamp": timestamp,
                }, f, ensure_ascii=False, indent=2)
            print(f"✅ Saved: {wav_path.name} ({wav_path.stat().st_size} bytes)")
            return True
        else:
            print("TTS generation failed", file=sys.stderr)
            return False

    except Exception as e:
        print(f"TTS error: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Speak text via Edge TTS")
    parser.add_argument("text", help="Text to speak")
    parser.add_argument("--voice", "-v", default=None, help="Voice name (default: es-ES-AlvaroNeural)")
    args = parser.parse_args()

    success = speak(args.text, args.voice)
    sys.exit(0 if success else 1)
