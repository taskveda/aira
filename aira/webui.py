import json
import re
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import tts
from . import voice
from .brain import Brain
from .config import AUDIO_DIR
from .executor import ToolExecutor

HOST, PORT = "127.0.0.1", 8756

PAGE = (Path(__file__).parent / "webui_page.html").read_text(encoding="utf-8")


class WebSession:
    def __init__(self):
        self.messages = []
        self.resolvers = {}
        self.pending_question = None
        self.status = "idle"          # idle | thinking | acting:<tool>
        self.speaking = False         # voice playback / voice-orb state

    def post_text(self, text, channel_override=None):
        self.messages.append({"role": "system", "content": text})

    def post_file(self, path, title="Aira output"):
        self.messages.append({"role": "system", "content": f"[file] {title}: {path}"})

    def ask_approval(self, question, force_auto=False):
        if force_auto:
            return True
        event = threading.Event()
        aid = f"web_{len(self.resolvers)}"
        self.resolvers[aid] = event
        self.pending_question = question
        answered = event.wait(timeout=600)
        self.resolvers.pop(aid, None)
        self.pending_question = None
        return answered and getattr(event, "approved", False)

    def resolve(self, approved):
        for event in self.resolvers.values():
            event.approved = approved
            event.set()


class Handler(BaseHTTPRequestHandler):
    session = WebSession()
    brain = None
    config = None
    summon_pending = False

    @classmethod
    def summon(cls):
        """Ask the popup to show itself (used when 'Hey Aira' wakes Aira)."""
        cls.summon_pending = True

    def log_message(self, *args):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/history":
            public = [{"role": m["role"], "content": m["content"]} for m in Handler.session.messages if m["role"] != "system"]
            return self._json({"history": public})
        if self.path == "/api/summon":
            pending = Handler.summon_pending
            Handler.summon_pending = False
            return self._json({"summon": pending})
        if self.path == "/api/pending":
            return self._json({"question": Handler.session.pending_question})
        if self.path == "/api/files":
            data_dir = Path.home() / "aira" / "data"
            files = []
            if data_dir.exists():
                for p in sorted(data_dir.iterdir(), key=lambda p: -p.stat().st_mtime if p.is_file() else 0):
                    if p.is_file():
                        files.append({"name": p.name, "size": p.stat().st_size, "modified": p.stat().st_mtime})
            return self._json({"files": files[:60]})
        if self.path == "/api/status":
            return self._json({
                "state": Handler.session.status,
                "speaking": Handler.session.speaking,
                "listening": bool(getattr(voice, "LISTENING", False)),
            })
        if self.path == "/api/memory":
            from . import memory_store
            try:
                return self._json({"memory": memory_store.bundle(), "facts": memory_store.query_facts(), "skills": memory_store.list_skills()})
            except Exception as exc:
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        if self.path == "/api/settings":
            return self._json({"hey_aira": bool(Handler.config.get("voice", {}).get("hey_aira", True))})
        if self.path.startswith("/api/audio/"):
            name = urllib.parse.unquote(self.path.rsplit("/", 1)[-1])
            audio = (AUDIO_DIR / name).resolve()
            if not audio.is_file() or audio.parent != AUDIO_DIR.resolve():
                return self._json({"error": "not found"}, 404)
            body = audio.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        ctype = self.headers.get("Content-Type", "").lower()
        if self.path == "/api/stt" and "audio/wav" in ctype:
            return self._stt()
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/chat":
            message = payload.get("message", "")
            Handler.session.messages.append({"role": "user", "content": message})
            low = re.sub(r"[^a-z\s]", "", message.lower()).strip()
            if re.fullmatch(r"(hey\s+)?aira", low):
                reply = "Hi Rohit — Aira here. What are we building today?"
                Handler.session.messages.append({"role": "assistant", "content": reply})
                return self._json({"reply": reply})
            try:
                Handler.session.status = "thinking"
                reply = Handler.brain.respond([{"role": "user", "content": message}] + [{"role": "user", "content": m["content"]} for m in Handler.session.messages if m["role"] == "user"][:-1])
            except Exception as exc:
                reply = f"Aira hit an error: {type(exc).__name__}: {exc}"
            finally:
                Handler.session.status = "idle"
            Handler.session.messages.append({"role": "assistant", "content": reply})
            return self._json({"reply": reply})
        if self.path == "/api/pending":
            Handler.session.resolve(bool(payload.get("approve")))
            return self._json({"ok": True})
        if self.path == "/api/tts":
            text = (payload.get("text") or "").strip()
            if not text:
                return self._json({"error": "no text"}, 400)
            try:
                audio = tts.generate(text, voice=Handler.config.tts_voice())
            except Exception as exc:
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return self._json({"url": f"/api/audio/{audio.name}"})
        self._json({"error": "not found"}, 404)

    def _stt(self):
        length = int(self.headers.get("Content-Length", 0))
        wav_bytes = self.rfile.read(length)
        if len(wav_bytes) < 100:
            return self._json({"error": "clip too short"}, 400)
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        try:
            tmp.write_bytes(wav_bytes)
            result = voice.transcribe(tmp, Handler.config)
        except Exception as exc:
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        finally:
            tmp.unlink(missing_ok=True)
        if not result.get("ok"):
            return self._json({"error": result.get("error", "stt failed")}, 500)
        return self._json({"text": result.get("text", "")})


def make_server(config):
    """Build (but don't run) the server, wiring the shared session + brain so
    both the popup/web UI and the background 'Hey Aira' listener use the same
    conversation, approval flow, and agentic engine."""
    session = Handler.session
    executor = ToolExecutor(session, config)
    Handler.brain = Brain(config, executor)
    Handler.config = config
    return ThreadingHTTPServer((HOST, PORT), Handler)


def start_web(config, open_browser=True):
    server = make_server(config)
    if open_browser:
        import webbrowser
        threading.Timer(0.6, webbrowser.open, args=(f"http://{HOST}:{PORT}/",)).start()
    print(f"Aira web UI running at http://{HOST}:{PORT}")
    server.serve_forever()
