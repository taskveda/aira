import subprocess

from . import tts
from .brain import Brain
from .executor import ToolExecutor


def _speak(text, cfg):
    """Play a reply out loud (Jerry-style). Off via tts.speak_cli: false."""
    if not cfg.get("tts", {}).get("speak_cli", True):
        return
    try:
        path = tts.generate(text, voice=cfg.tts_voice())
        subprocess.run(["afplay", str(path)], timeout=180)
    except Exception as exc:
        print(f"[tts] {type(exc).__name__}: {exc}")


class CliSession:
    def __init__(self):
        self.resolvers = {}

    def post_text(self, text, channel_override=None):
        print(text)

    def post_file(self, path, title="Ras output"):
        print(f"[file] {title}: {path}")

    def ask_approval(self, action_id, question, force_auto=False):
        if force_auto:
            return True
        try:
            answer = input(f"Ras asks: {question} (y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("[denied by default]")
            return False
        return answer in ("y", "yes", "approve")

    def make_executor(self):
        return ToolExecutor(self, self.config)


def run(cfg, once=None):
    session = CliSession()
    from .config import Config
    session.config = cfg
    executor = ToolExecutor(session, cfg)
    brain = Brain(cfg, executor)
    history = []
    if once:
        history = [{"role": "user", "content": once}]
        print(brain.run(history))
        return
    print("Ras CLI — type a task (or 'quit'). Destructive commands ask for approval.")
    while True:
        try:
            prompt = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not prompt:
            continue
        if prompt.lower() in ("quit", "exit"):
            break
        history.append({"role": "user", "content": prompt})
        reply = brain.run(history)
        print("\nRas:", reply)
        _speak(reply, cfg)
        history.append({"role": "assistant", "content": ""})
