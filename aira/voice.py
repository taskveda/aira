"""Voice layer for Aira — "Hey Aira" hands-free on macOS.

Pipeline: ffmpeg (mic capture) → Cloudflare Workers AI Whisper (STT)
→ Brain (think/act) → edge-tts + afplay (speak).

Zero new dependencies: ffmpeg ships via Homebrew, Whisper uses the same
Cloudflare account already in config.yaml, TTS is the existing edge-tts.
"""

import difflib
import re
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from . import tts
from .config import DATA

STT_MODEL = "@cf/openai/whisper-large-v3-turbo"

WAKE_RE = re.compile(r"\b(?:hey\s+)?airas?\b", re.IGNORECASE)

# Tolerant matcher: Whisper/Live STT hears "Hey Aira" as many spellings —
# "Era", "Aida", "Eyra", "Ayra", "Aira", "Aidas", … A fuzzy match on the
# spoken word (not the exact spelling) is what makes the wake word reliable.
_WAKE_TARGETS = ("aira", "eira", "era", "aida", "eyra", "ayra", "ara")


def is_wake(text):
    """True if the transcript sounds like the Aira wake word (fuzzy, not exact)."""
    if not text:
        return False
    words = re.findall(r"[a-z']+", text.lower())
    for word in words:
        if not 2 <= len(word) <= 6:
            continue
        for target in _WAKE_TARGETS:
            if "hey" not in words and word == "hey":
                continue
            ratio = difflib.SequenceMatcher(None, word, target).ratio()
            need = 0.62 if "hey" in words else 0.7
            if ratio >= need:
                return True
    return False
APPROVE_RE = re.compile(r"\b(?:yes|yep|yeah|approve|okay|ok|do it|go ahead)\b", re.IGNORECASE)
DENY_RE = re.compile(r"\b(?:no|nope|deny|cancel|stop|don't|dont)\b", re.IGNORECASE)


_MIC_DEVICE = None
_MIC_OK = None  # tri-state cache: None=untested, True/False from is_mic_available()
_MIC_GUIDANCE_SHOWN = False
_MIC_FAILS = 0    # consecutive record_mic failures (drives backoff)
LISTENING = False # True while the mic is capturing (drives the UI voice-orb)


def _ffmpeg_run(cmd, timeout):
    """Run ffmpeg with a hard kill on timeout so a blocked/pending microphone
    can never wedge the voice loop into long stalls."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        proc.returncode = 1
        out, err = "", ""
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _mic_guidance():
    """Print mic-permission guidance exactly once, not on every retry."""
    global _MIC_GUIDANCE_SHOWN
    if _MIC_GUIDANCE_SHOWN:
        return
    _MIC_GUIDANCE_SHOWN = True
    print("[mic] Fix mic access: System Settings → Privacy & Security → Microphone → enable your terminal/app.")


def reset_mic_cache():
    """Forget the availability/device caches so a later call re-probes (use
    when the user may have just granted mic permission)."""
    global _MIC_OK
    _MIC_OK = None


def _reset_mic_failures():
    global _MIC_FAILS
    _MIC_FAILS = 0


def detect_mic_device():
    """Return the ffmpeg avfoundation device id for the built-in mic.

    'default' is unreliable on some Macs (it can point at a virtual device like
    Teams that captures nothing), so we look for the real microphone once and
    cache it. Falls back to ':0' (first audio device) — not the classic 'default'.
    """
    global _MIC_DEVICE
    if _MIC_DEVICE:
        return _MIC_DEVICE
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=10,
        )
        out = proc.stderr + proc.stdout
        idx = None
        for line in out.splitlines():
            low = line.lower()
            if "microphone" in low or "built-in" in low:
                matches = re.findall(r"\[(\d+)\]\s+", line)
                if matches:
                    idx = int(matches[-1])
                    break
        _MIC_DEVICE = f":{idx}" if idx is not None else ":0"
    except Exception:
        _MIC_DEVICE = ":0"
    return _MIC_DEVICE


def is_mic_available():
    """True if ffmpeg can actually open the built-in mic right now.

    The pre-check matters: under launchd / without mic permission, ffmpeg
    silently BLOCKS on -i :0 forever instead of erroring, which previously
    made the wake-word loop spin on 22s timeouts forever. We probe once with a
    hard subprocess timeout and cache the result so voice fails fast (and the
    rest of Aira keeps working) instead of drowning the logs.
    """
    global _MIC_OK
    if _MIC_OK is not None:
        return _MIC_OK
    device = detect_mic_device()
    probe = Path(tempfile.mktemp(suffix=".probe.wav"))
    try:
        proc = _ffmpeg_run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation", "-i", device,
             "-t", "0.3", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(probe)],
            timeout=4,
        )
        _MIC_OK = proc.returncode == 0 and probe.exists() and probe.stat().st_size > 0
    except subprocess.TimeoutExpired:
        _MIC_OK = False
    except Exception:
        _MIC_OK = False
    probe.unlink(missing_ok=True)
    if not _MIC_OK:
        _mic_guidance()
        print("[mic] mic unavailable (permission or no device). Voice wake disabled; text/Slack still work.")
    return _MIC_OK


def record_mic(out_path, seconds):
    """Record <seconds> of mono 16k PCM from the built-in mic via ffmpeg.

    Fails fast (short probe timeout) if the mic can't be opened so a broken
    mic can never wedge the wake-word loop into 22s timeouts. On a timeout
    the ffmpeg process is hard-killed and the mic cache is reset so the next
    is_mic_available() re-probes (e.g. right after the user grants access).
    """
    global LISTENING
    LISTENING = True
    try:
        return _record_mic(out_path, seconds)
    finally:
        LISTENING = False


def _record_mic(out_path, seconds):
    global _MIC_FAILS
    device = detect_mic_device()
    try:
        proc = _ffmpeg_run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation", "-i", device,
             "-t", str(seconds), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_path)],
            timeout=seconds + 6,
        )
    except subprocess.TimeoutExpired:
        _MIC_FAILS += 1
        reset_mic_cache()
        _mic_guidance()
        return {"ok": False, "error": "mic record timed out (permission or blocked device)"}
    if proc.returncode != 0:
        print(f"[record_mic] ffmpeg failed with code {proc.returncode}, stderr={proc.stderr}, stdout={proc.stdout}")
    ok = proc.returncode == 0 and Path(out_path).exists() and Path(out_path).stat().st_size > 0
    if not ok:
        # Last resort: fall back to the classic 'default'.
        try:
            proc = _ffmpeg_run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation", "-i", "default",
                 "-t", str(seconds), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_path)],
                timeout=seconds + 6,
            )
        except subprocess.TimeoutExpired:
            _MIC_FAILS += 1
            reset_mic_cache()
            _mic_guidance()
            return {"ok": False, "error": "mic record timed out (permission or blocked device)"}
        if proc.returncode != 0:
            print(f"[record_mic] fallback failed with code {proc.returncode}, stderr={proc.stderr}, stdout={proc.stdout}")
        ok = proc.returncode == 0 and Path(out_path).exists() and Path(out_path).stat().st_size > 0
    if not ok:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        return {"ok": False, "error": err[-1] if err else "no mic audio captured"}
    _reset_mic_failures()
    return {"ok": True, "path": str(out_path), "seconds": seconds}


def transcribe(wav_path, config):
    """Transcribe a wav file with Cloudflare Workers AI Whisper (free tier)."""
    api_key = config.api_key()
    base = config.base_url().rstrip("/")
    if not api_key or "api.cloudflare.com" not in base:
        return {"ok": False, "error": "voice needs Cloudflare Workers AI config + DEEPSEEK_API_KEY in ~/aira/.env"}
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


def _mean_volume_db(wav_path):
    """Return the mean audio level in dB from ffmpeg volumedetect, or None."""
    proc = subprocess.run(
        ["ffmpeg", "-i", str(wav_path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=30,
    )
    for line in (proc.stderr or "").splitlines():
        if "mean_volume" in line:
            try:
                return float(line.split("mean_volume:")[1].split("dB")[0])
            except (ValueError, IndexError):
                return None
    return None


def is_silent(wav_path, threshold_db=-35.0):
    """True if the clip is effectively silence. Cheap local check via ffmpeg
    so we don't burn a Cloudflare STT call on an empty room."""
    vol = _mean_volume_db(wav_path)
    return vol is None or vol < threshold_db


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

    def post_file(self, path, title="Aira output"):
        print(f"[file] {title}: {path}")

    def ask_approval(self, action_id, question, force_auto=False):
        if force_auto:
            return True
        return confirm(question, self.config)

    def make_executor(self):
        from .executor import ToolExecutor
        return ToolExecutor(self, self.config)


def _greeting(first=False):
    """Time-of-day greeting for a wake-up."""
    hour = time.localtime().tm_hour
    if hour < 12:
        part = "good morning"
    elif hour < 17:
        part = "good afternoon"
    else:
        part = "good evening"
    if first:
        return f"Hey Rohit, {part}. How are you doing?"
    return f"Hey Rohit, {part}. What do you need?"


def run_voice(cfg):
    """Hands-free loop: listen for the wake word, then hear + do + speak."""
    from .brain import Brain

    if not cfg.get("voice", {}).get("hey_aira", True):
        print("[voice] 'hey_aira' is disabled in config.yaml — wake-word listening is off. Set voice.hey_aira: true to enable.")
        return 0

    session = VoiceSession(cfg)
    brain = Brain(cfg, session.make_executor())

    poll = float(cfg.get("voice", {}).get("poll_seconds", 2.5))
    utter = float(cfg.get("voice", {}).get("utterance_seconds", 10))
    first_greeting = True
    history = []

    print('Aira voice mode — say "Hey Aira" to wake me. Ctrl+C to stop.')
    mic_ok = is_mic_available()
    if not mic_ok:
        print("[voice] microphone unavailable — I'll keep watching and resume the moment you grant access. (Settings only, below)")
    with tempfile.TemporaryDirectory() as tmpdir:
        probe = Path(tmpdir) / "probe.wav"
        utterance = Path(tmpdir) / "utterance.wav"
        while True:
            try:
                if not mic_ok or _MIC_FAILS >= 3:
                    time.sleep(15)
                    reset_mic_cache()
                    _reset_mic_failures()
                    mic_ok = is_mic_available()
                    continue
                rec = record_mic(probe, poll)
                if not rec["ok"]:
                    print(f"[mic] {rec['error']}")
                    _mic_guidance()
                    time.sleep(3)
                    continue
                vol = _mean_volume_db(probe)
                print(f"[probe] mean={vol}dB silent={is_silent(probe)}")
                if is_silent(probe):
                    continue
                stt = transcribe(probe, cfg)
                if not stt["ok"]:
                    print(f"[stt] {stt['error']}")
                    time.sleep(1)
                    continue
                heard = (stt.get("text") or "").strip()
                print(f"[heard] {heard!r}")
                if not heard or not is_wake(heard):
                    continue
                # Woken up — answer like Siri, then start listening for the task.
                if first_greeting:
                    first_greeting = False
                    wake_reply = _greeting(True)          # "Hey Rohit, good morning. How are you doing?"
                else:
                    wake_reply = "Yes, Rohit? What do you need?"
                beep()
                speak(wake_reply, cfg)
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
                print(f"Aira: {reply}")
                speak(reply, cfg)
            except KeyboardInterrupt:
                print("\nVoice mode stopped.")
                return 0
            except Exception as exc:  # keep the loop alive, report honestly
                print(f"[voice] {type(exc).__name__}: {exc}")
                time.sleep(1)

