"""Full-fledged Aira: one always-on process that is BOTH the popup/web
assistant AND the hands-free \"Hey Aira\" assistant, sharing a single brain,
session (history + approvals), personality/memory, and server.

- Text it (popup or browser): /api/chat -> shared Brain
- Say \"Hey Aira\": wake-word listener -> same shared Brain, spoken reply,
  and the popup is summoned so the exchange shows up on screen.
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path

from . import voice as voice_mod
from .webui import make_server, Handler, HOST, PORT

# Debug: log the detected mic device at startup
print(f"[assistant] using mic device: {voice_mod.detect_mic_device()}")


def _ask(text):
    """Route a message (typed or spoken) through the shared brain + history."""
    Handler.session.messages.append({"role": "user", "content": text})
    prior = [
        {"role": "user", "content": m["content"]}
        for m in Handler.session.messages
        if m["role"] == "user"
    ][-15:]
    try:
        reply = Handler.brain.respond(prior + [{"role": "user", "content": text}])
    except Exception as exc:
        reply = f"Aira hit an error: {type(exc).__name__}: {exc}"
    Handler.session.messages.append({"role": "assistant", "content": reply})
    return reply


def _greeting(first=False):
    hour = time.localtime().tm_hour
    if hour < 12:
        part = "good morning"
    elif hour < 17:
        part = "good afternoon"
    else:
        part = "good evening"
    if first:
        return f"Hey Rohit, {part}. How are you doing?"
    return f"Yes, Rohit? What do you need?"


def _open_popup():
    app = os.path.expanduser("~/aira/AiraPopup.app")
    if os.path.isdir(app):
        subprocess.Popen(["open", app])
        return True
    return False


def run_assistant(cfg):
    if not _open_popup():
        print("AiraPopup.app not built yet — run ~/aira/build_popup.sh first.")
        # Still run the listener + web UI so text works; popup just won't appear.
    import threading

    server = make_server(cfg)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Aira assistant live — text in the popup/browser (http://{HOST}:{PORT}) or say \"Hey Aira\".")

    if not cfg.get("voice", {}).get("hey_aira", True):
        print("[assistant] voice.hey_aira is disabled in config.yaml — hands-free wake is off. Text (popup/browser) still works.")
        while True:   # keep the web/popup server alive; text-only
            time.sleep(3600)

    poll = float(cfg.get("voice", {}).get("poll_seconds", 2.5))
    utter = float(cfg.get("voice", {}).get("utterance_seconds", 10))
    first_greeting = True

    print('Aira wake-word listener on — say "Hey Aira" to summon + talk. Ctrl+C to stop.')
    mic_ok = voice_mod.is_mic_available()
    if not mic_ok:
        print("[assistant] microphone unavailable — running text-only (popup/browser still works).")
    with tempfile.TemporaryDirectory() as tmpdir:
        probe = Path(tmpdir) / "probe.wav"
        utterance = Path(tmpdir) / "utterance.wav"
        while True:
            try:
                if not mic_ok:
                    time.sleep(15)
                    voice_mod.reset_mic_cache()
                    mic_ok = voice_mod.is_mic_available()
                    continue
                rec = voice_mod.record_mic(probe, poll)
                if not rec["ok"]:
                    print(f"[mic] {rec['error']} — check mic permission for the terminal app")
                    time.sleep(3)
                    continue
                if voice_mod.is_silent(probe):
                    continue
                stt = voice_mod.transcribe(probe, cfg)
                if not stt["ok"]:
                    print(f"[stt] {stt['error']}")
                    time.sleep(1)
                    continue
                heard = (stt.get("text") or "").strip()
                print(f"[heard] {heard!r}")
                if not heard or not voice_mod.is_wake(heard):
                    continue
                voice_mod.beep()
                Handler.summon()                       # panel rises first…
                voice_mod.speak(_greeting(first_greeting), cfg)  # …then greet aloud (edge-tts), right as it appears
                first_greeting = False
                rec2 = voice_mod.record_mic(utterance, utter)    # …then listen for the task
                if not rec2["ok"]:
                    continue
                stt2 = voice_mod.transcribe(utterance, cfg)
                if not stt2["ok"]:
                    voice_mod.speak("Didn't catch that. Say it again.", cfg)
                    continue
                user_text = (stt2.get("text") or "").strip()
                if not user_text:
                    voice_mod.speak("Didn't catch that. Say it again.", cfg)
                    continue
                print(f"\nYou: {user_text}")
                reply = _ask(user_text)
                print(f"Aira: {reply}")
                voice_mod.speak(reply, cfg)
            except KeyboardInterrupt:
                print("\nAira assistant stopped.")
                return 0
            except Exception as exc:
                print(f"[assistant] {type(exc).__name__}: {exc}")
                time.sleep(1)
