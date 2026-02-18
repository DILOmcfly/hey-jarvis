"""
🎙 Hey Jarvis V2 — Voice Wake Word Listener
=============================================
Listens for "Hey Jarvis", records voice with Silero VAD,
saves WAV to shared folder for WSL2 transcription.

V2 improvements:
- Pre-buffer (captures audio before wake word confirmation)
- Conversation mode (10s window to keep talking without re-triggering)
- 3 feedback sounds: ding (listening), done (recorded), error
- Abort if no speech detected in 5s
- VAD reset between recordings
- Max recording 2 min
- Rotated file logging

Runs on Windows natively (needs microphone access).
WSL2 has no mic access — that's why this runs on Windows.
"""

import os
import sys
import wave
import time
import uuid
import logging
import collections
import threading
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

import numpy as np
import pyaudio

# ─── Fix headless stdout (pythonw.exe) ───────────────────────────────────
if sys.stdout is None or not hasattr(sys.stdout, 'write'):
    _devnull = open(os.devnull, 'w')
    sys.stdout = _devnull
    sys.stderr = _devnull

from openwakeword.model import Model as OWWModel

# ─── Configuration ───────────────────────────────────────────────────────

# Wake word
WAKE_THRESHOLD = float(os.environ.get("HJ_WAKE_THRESHOLD", "0.5"))

# Audio settings
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_MS = 80
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_MS / 1000)  # 1280 samples
FORMAT = pyaudio.paInt16
VAD_CHUNK_SIZE = 512  # Silero VAD expects 512 samples at 16kHz

# Recording
SILENCE_TIMEOUT_SEC = 2.0   # Stop after 2s silence
MAX_RECORDING_SEC = 120     # Max 2 minutes
NO_SPEECH_ABORT_SEC = 5.0   # Abort if no speech in 5s
PRE_BUFFER_SEC = 0.5        # Keep 0.5s audio before wake word

# Conversation mode
CONVERSATION_WINDOW_SEC = 10.0  # After response, listen again for 10s

# Output
AUDIO_OUTPUT_DIR = Path(os.environ.get(
    "HJ_AUDIO_DIR",
    os.path.join(os.path.expanduser("~"), "oye-ikigai-audio")
))

# Sounds
SOUNDS_DIR = Path(__file__).parent / "sounds"
SOUND_DING = SOUNDS_DIR / "ding.wav"
SOUND_DONE = SOUNDS_DIR / "done.wav"
SOUND_ERROR = SOUNDS_DIR / "error.wav"

# Logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("hey-jarvis")
logger.setLevel(logging.INFO)

_fh = RotatingFileHandler(
    str(LOG_DIR / "hey_jarvis.log"),
    maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_fh.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(_ch)


# ─── Silero VAD ──────────────────────────────────────────────────────────

class SileroVAD:
    """Voice Activity Detection using Silero VAD."""

    def __init__(self, threshold: float = 0.4):
        import torch
        self.torch = torch
        self.threshold = threshold
        self.model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            trust_repo=True
        )
        self.model.eval()
        logger.info("Silero VAD loaded (threshold=%.2f)", threshold)

    def is_speech(self, audio_chunk_int16: np.ndarray) -> bool:
        audio_float = audio_chunk_int16.astype(np.float32) / 32768.0
        tensor = self.torch.from_numpy(audio_float)
        confidence = self.model(tensor, SAMPLE_RATE).item()
        return confidence > self.threshold

    def reset(self):
        """Reset VAD state between recordings."""
        self.model.reset_states()


# ─── Audio Feedback ──────────────────────────────────────────────────────

def play_sound(sound_path: Path):
    """Play a WAV sound file (non-blocking)."""
    if not sound_path.exists():
        return
    try:
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(str(sound_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            import subprocess
            subprocess.Popen(["aplay", str(sound_path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logger.warning("Sound playback failed: %s", e)


# ─── Pre-buffer ──────────────────────────────────────────────────────────

class PreBuffer:
    """Circular buffer that keeps the last N seconds of audio chunks."""

    def __init__(self, seconds: float, chunk_size: int, sample_rate: int):
        # How many chunks fit in the buffer
        samples_per_chunk = chunk_size
        chunks_per_second = sample_rate / samples_per_chunk
        max_chunks = int(seconds * chunks_per_second)
        self.buffer = collections.deque(maxlen=max(max_chunks, 1))

    def add(self, chunk: bytes):
        self.buffer.append(chunk)

    def get_all(self) -> list:
        return list(self.buffer)

    def clear(self):
        self.buffer.clear()


# ─── Recording ───────────────────────────────────────────────────────────

def record_with_vad(stream, vad: SileroVAD, pre_frames: list = None) -> bytes | None:
    """Record audio until silence detected. Returns PCM bytes or None if no speech."""
    logger.info("🎤 Recording... (speak now)")
    frames = list(pre_frames or [])
    silence_start = None
    first_speech_detected = False
    recording_start = time.time()

    while True:
        elapsed = time.time() - recording_start

        if elapsed > MAX_RECORDING_SEC:
            logger.warning("Max recording duration reached (%ds)", MAX_RECORDING_SEC)
            break

        data = stream.read(VAD_CHUNK_SIZE, exception_on_overflow=False)
        frames.append(data)

        audio_array = np.frombuffer(data, dtype=np.int16)
        has_speech = vad.is_speech(audio_array)

        if has_speech:
            first_speech_detected = True
            silence_start = None
        else:
            # Abort if no speech detected within NO_SPEECH_ABORT_SEC
            if not first_speech_detected and elapsed > NO_SPEECH_ABORT_SEC:
                logger.info("⏳ No speech detected in %.0fs, aborting", NO_SPEECH_ABORT_SEC)
                return None

            if first_speech_detected:
                if silence_start is None:
                    silence_start = time.time()
                elif time.time() - silence_start > SILENCE_TIMEOUT_SEC:
                    logger.info("🔇 Silence detected (%.1fs), stopping", SILENCE_TIMEOUT_SEC)
                    break

    pcm_data = b"".join(frames)
    duration = len(pcm_data) / (SAMPLE_RATE * 2)
    logger.info("📝 Recorded %.1fs of audio", duration)

    if duration < 0.5:
        logger.warning("Recording too short (%.1fs), discarding", duration)
        return None

    return pcm_data


def save_wav(pcm_data: bytes) -> Path:
    """Save PCM data as WAV file in the shared audio folder."""
    AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"ikigai_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.wav"
    filepath = AUDIO_OUTPUT_DIR / filename

    with wave.open(str(filepath), 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)

    duration = len(pcm_data) / (SAMPLE_RATE * 2)
    logger.info("💾 Saved: %s (%.1fs)", filename, duration)
    return filepath


# ─── Quick Commands ──────────────────────────────────────────────────────

# These are handled locally without LLM — instant response
QUICK_COMMANDS = {}
# Placeholder for future: {"hora": lambda: speak(datetime.now().strftime("%H:%M"))}
# Not implemented yet — all commands go to OpenClaw for now


# ─── Main Loop ───────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("🎙 Hey Jarvis V2 — Voice Listener")
    logger.info("=" * 60)
    logger.info("Output dir:   %s", AUDIO_OUTPUT_DIR)
    logger.info("Wake threshold: %.2f", WAKE_THRESHOLD)
    logger.info("Conversation window: %.0fs", CONVERSATION_WINDOW_SEC)

    # Load wake word model (only hey_jarvis — not all built-ins)
    logger.info("Loading openWakeWord (hey_jarvis only)...")
    oww = OWWModel(
        wakeword_models=["hey_jarvis_v0.1"],
        inference_framework="onnx"
    )
    logger.info("Wake word model loaded ✅")

    logger.info("Loading Silero VAD...")
    vad = SileroVAD(threshold=0.4)
    logger.info("VAD loaded ✅")

    # Pre-buffer for capturing audio before wake word confirmation
    pre_buffer = PreBuffer(PRE_BUFFER_SEC, CHUNK_SIZE, SAMPLE_RATE)

    # Init audio
    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE
    )

    logger.info("")
    logger.info("👂 Listening for 'Hey Jarvis'...")
    logger.info("   Press Ctrl+C to stop")
    logger.info("")

    conversation_until = 0  # timestamp until conversation mode is active

    try:
        while True:
            data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            audio_array = np.frombuffer(data, dtype=np.int16)
            pre_buffer.add(data)

            now = time.time()
            in_conversation = now < conversation_until

            # In conversation mode: check VAD directly (no wake word needed)
            if in_conversation:
                vad_array = audio_array[:VAD_CHUNK_SIZE] if len(audio_array) >= VAD_CHUNK_SIZE else audio_array
                if vad.is_speech(vad_array):
                    logger.info("🔄 Conversation mode — speech detected, recording...")
                    play_sound(SOUND_DING)
                    time.sleep(0.05)

                    pre_frames = pre_buffer.get_all()
                    pre_buffer.clear()
                    vad.reset()

                    pcm_data = record_with_vad(stream, vad, pre_frames)

                    if pcm_data:
                        play_sound(SOUND_DONE)
                        save_wav(pcm_data)
                        conversation_until = time.time() + CONVERSATION_WINDOW_SEC
                    else:
                        play_sound(SOUND_ERROR)

                    vad.reset()
                    oww.reset()
                    logger.info("👂 Listening... (conversation mode: %.0fs left)",
                                max(0, conversation_until - time.time()))
                continue

            # Normal mode: check wake word
            prediction = oww.predict(audio_array)

            for model_name, score in prediction.items():
                if score > WAKE_THRESHOLD:
                    logger.info("🔥 Wake word '%s' detected! (score=%.3f)", model_name, score)
                    play_sound(SOUND_DING)
                    time.sleep(0.05)

                    # Grab pre-buffer frames
                    pre_frames = pre_buffer.get_all()
                    pre_buffer.clear()
                    vad.reset()

                    pcm_data = record_with_vad(stream, vad, pre_frames)

                    if pcm_data:
                        play_sound(SOUND_DONE)
                        save_wav(pcm_data)
                        # Enter conversation mode
                        conversation_until = time.time() + CONVERSATION_WINDOW_SEC
                        logger.info("💬 Conversation mode ON for %.0fs", CONVERSATION_WINDOW_SEC)
                    else:
                        play_sound(SOUND_ERROR)
                        logger.info("No speech detected, back to listening")

                    vad.reset()
                    oww.reset()
                    pre_buffer.clear()

                    logger.info("👂 Listening for 'Hey Jarvis'...")
                    break

    except KeyboardInterrupt:
        logger.info("\n👋 Stopping listener...")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()
        logger.info("Bye!")


if __name__ == "__main__":
    main()
