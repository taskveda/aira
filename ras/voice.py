"""Voice layer for Ras — "Hey Ras" hands-free on macOS.

Pipeline: ffmpeg (mic capture) → Cloudflare Workers AI Whisper (STT)
→ Brain (think/act) → edge-tts + afplay (speak).

Zero new dependencies: ffmpeg ships via Homebrew, Whisper uses the same
Cloudflare account already in config.yaml, TTS is the existing edge-tts.
"""

import re
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from . import tts
from .config import DATA

STT_MODEL = "@cf/openai/whisper-large-v3-turbo"

WAKE_RE = re.compile(r"\b(?:hey\s+)?rass?\b", re.IGNORECASE)
APPROVE_RE = re.compile(r"\b(?:yes|yep|yeah|approve|okay|ok|do it|go ahead)\b", re.IGNORECASE)
DENY_RE = re.compile(r"\b(?:no|nope|deny|cancel|stop|don't|dont)\b", re.IGNORECASE)


def record_mic(out_path, seconds):
    """Record <seconds> of mono 16k PCM from the default mic via ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "avfoundation", "-i", "default",
        "-t", str(seconds), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 20)
    ok = proc.returncode == 0 and Path(out_path).exists() and Path(out_path).stat().st_size > 0
    if not ok:
        # Fallback: first audio device by index (":0" = audio 0, no video).
        proc = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation", "-i", ":0",
             "-t", str(seconds), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_path)],
            capture_output=True, text=True, timeout=seconds + 20,
        )
        ok = proc.returncode == 0 and Path(out_path).exists() and Path(out_path).stat().st_size > 0
    if not ok:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        return {"ok": False, "error": err[-1] if err else "no mic audio captured"}
    return {"ok": True, "path": str(out_path), "seconds": seconds}


def transcribe(wav_path, config):
    """Transcribe a wav file with Cloudflare Workers AI Whisper (free tier)."""
    api_key = config.api_key()
    base = config.base_url().rstrip("/")
    if not api_key or "api.cloudflare.com" not in base:
        return {"ok": False, "error": "voice needs Cloudflare Workers AI config + DEEPSEEK_API_KEY in ~/ras/.env"}
    # The REST run route is /ai/run/<model> — the /v1 suffix only applies
    # to the OpenAI-compatible chat endpoint, so strip it if present.
    run_base = base[: -len("/v1")] if base.endswith("/v1") else base
    url = f"{run_base}/run/{STT_MODEL}"
    try:
        with open(wav_path, "rb") as fh:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "audio/wav"},
                data=fh,
                timeout=90,
            )
    except requests.RequestException as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if resp.status_code != 200:
        return {"ok": False, "error": f"STT HTTP {resp.status_code}: {resp.text[:200]}"}
    text = ((resp.json().get("result") or {}).get("text") or "").strip()
    return {"ok": True, "text": text}


def is_silent(wav_path, threshold_db=-35.0):
    """True if the clip is effectively silence. Cheap local check via ffmpeg
    so we don't burn a Cloudflare STT call on an empty room."""
    proc = subprocess.run(
        ["ffmpeg", "-i", str(wav_path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=30,
    )
    for line in (proc.stderr or "").splitlines():
        if "mean_volume" in line:
            try:
                return float(line.split("mean_volume:")[1].split("dB")[0]) < threshold_db
            except (ValueError, IndexError):
                return False
    return True


def speak(text, config):
    """Generate speech with edge-tts and play it aloud. Returns the audio path."""
    if not text:
        return None
    path = tts.generate(text, voice=config.tts_voice())
    subprocess.run(["afplay", str(path)], timeout=180)
    return path


def beep():
    """Short attention beep before listening for the actual request."""
    beep_path = DATA / "beep.wav"
    if not beep_path.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=frequency=880:duration=0.12", "-ac", "1", "-ar", "22050", str(beep_path)],
            capture_output=True, timeout=30,
        )
    if beep_path.exists():
        subprocess.run(["afplay", str(beep_path)], timeout=10)


def confirm(question, config):
    """Ask a yes/no question aloud, listen for the answer, return bool."""
    speak(question, config)
    clip = Path(tempfile.mktemp(suffix=".wav"))
    try:
        rec = record_mic(clip, 4)
        if not rec["ok"]:
            return False
        stt = transcribe(clip, config)
        if not stt["ok"]:
            return False
        text = (stt.get("text") or "").lower()
        if DENY_RE.search(text) and not APPROVE_RE.search(text):
            return False
        return bool(APPROVE_RE.search(text))
    finally:
        clip.unlink(missing_ok=True)


class VoiceSession:
    """Session adapter so the Brain/executor work in voice mode.
    Approvals are asked aloud and answered by voice; files post to the terminal."""

    def __init__(self, config):
        self.config = config

    def post_text(self, text, channel_override=None):
        print(text)

    def post_file(self, path, title="Ras output"):
        print(f"[file] {title}: {path}")

    def ask_approval(self, action_id, question, force_auto=False):
        if force_auto:
            return True
        return confirm(question, self.config)

    def make_executor(self):
        from .executor import ToolExecutor
        return ToolExecutor(self, self.config)


def run_voice(cfg):
    """Hands-free loop: listen for the wake word, then hear + do + speak."""
    from .brain import Brain

    session = VoiceSession(cfg)
    brain = Brain(cfg, session.make_executor())

    poll = float(cfg.get("voice", {}).get("poll_seconds", 2.5))
    utter = float(cfg.get("voice", {}).get("utterance_seconds", 10))
    first_greeting = True
    history = []

    print('Ras voice mode — say "Hey Ras" to wake me. Ctrl+C to stop.')
    with tempfile.TemporaryDirectory() as tmpdir:
        probe = Path(tmpdir) / "probe.wav"
        utterance = Path(tmpdir) / "utterance.wav"
        while True:
            try:
                rec = record_mic(probe, poll)
                if not rec["ok"]:
                    print(f"[mic] {rec['error']} — check mic permission for the terminal app")
                    time.sleep(3)
                    continue
                if is_silent(probe):
                    continue
                stt = transcribe(probe, cfg)
                if not stt["ok"]:
                    print(f"[stt] {stt['error']}")
                    time.sleep(1)
                    continue
                heard = (stt.get("text") or "").strip()
                if not heard or not WAKE_RE.search(heard):
                    continue
                # Woken up.
                if first_greeting:
                    first_greeting = False
                    beep()
                    speak("Yo, I'm Ras. What are we building today?", cfg)
                else:
                    beep()
                rec2 = record_mic(utterance, utter)
                if not rec2["ok"]:
                    continue
                stt2 = transcribe(utterance, cfg)
                if not stt2["ok"]:
                    speak("Didn't catch that. Say it again.", cfg)
                    continue
                user_text = (stt2.get("text") or "").strip()
                if not user_text:
                    speak("Didn't catch that. Say it again.", cfg)
                    continue
                print(f"\nYou: {user_text}")
                history.append({"role": "user", "content": user_text})
                reply = brain.run(history)
                history.append({"role": "assistant", "content": reply})
                print(f"Ras: {reply}")
                speak(reply, cfg)
            except KeyboardInterrupt:
                print("\nVoice mode stopped.")
                return 0
            except Exception as exc:  # keep the loop alive, report honestly
                print(f"[voice] {type(exc).__name__}: {exc}")
                time.sleep(1)

