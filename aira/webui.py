import json
import re
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import tts
from . import voice
from . import productivity
from .brain import Brain
from .config import AUDIO_DIR
from .executor import ToolExecutor

HOST, PORT = "127.0.0.1", 8756

DATA_DIR = Path.home() / "aira" / "data"


def now_iso():
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _file_list():
    files = []
    if DATA_DIR.exists():
        for p in sorted(DATA_DIR.iterdir(), key=lambda p: -p.stat().st_mtime if p.is_file() else 0):
            if p.is_file():
                files.append({"name": p.name, "size": p.stat().st_size, "modified": p.stat().st_mtime})
    return files[:60]


def _save_settings(payload):
    """Persist UI-settable runtime settings back to config.yaml (e.g. Hey Aira toggle)."""
    import yaml
    path = Path.home() / "aira" / "config.yaml"
    raw = {}
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except Exception:
            raw = {}
    changed = False
    if "hey_aira" in payload:
        raw.setdefault("voice", {})["hey_aira"] = bool(payload["hey_aira"])
        Handler.config.raw.setdefault("voice", {})["hey_aira"] = bool(payload["hey_aira"])
        changed = True
    if changed:
        try:
            path.write_text(yaml.safe_dump(raw, sort_keys=False))
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, **{k: v for k, v in payload.items()}}

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
            return self._json({"files": _file_list()})
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
        if self.path == "/api/tasks":
            tasks = productivity.reminder_list(include_done=True)
            due = [r for r in tasks if not r.get("done") and r.get("due_at", "") <= now_iso()]
            return self._json({"tasks": tasks, "pending": len(due), "done": sum(1 for r in tasks if r.get("done"))})
        if self.path == "/api/calendar":
            return self._json(productivity.calendar_list(days_ahead=7))
        if self.path == "/api/knowledge":
            return self._json({"items": productivity.knowledge_list()})
        if self.path == "/api/automations":
            jobs = Handler.config.get("jobs", []) or []
            return self._json({"jobs": jobs})
        if self.path == "/api/integrations":
            return self._json(productivity.connector_status())
        if self.path == "/api/insights":
            from . import memory_store
            skills = memory_store.list_skills()
            tasks = productivity.reminder_list(include_done=True)
            return self._json({
                "skills": len(skills),
                "facts": len(memory_store.query_facts()),
                "files": len(_file_list()),
                "tasks_done": sum(1 for r in tasks if r.get("done")),
            })
        if self.path.startswith("/api/knowledge"):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            q = (qs.get("q") or [""])[0]
            if q:
                limit = int((qs.get("limit") or ["5"])[0])
                return self._json(productivity.knowledge_search(q, limit=limit))
            return self._json({"items": productivity.knowledge_list()})
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
        if self.path == "/api/tasks":
            text = (payload.get("text") or "").strip()
            due = (payload.get("due_at") or "").strip() or now_iso()
            if not text:
                return self._json({"error": "no text"}, 400)
            return self._json(productivity.reminder_add(text, due))
        if self.path == "/api/tasks/done":
            rid = payload.get("id")
            if rid is None:
                return self._json({"error": "no id"}, 400)
            return self._json(productivity.reminder_done(rid))
        if self.path == "/api/calendar":
            title = (payload.get("title") or "").strip()
            start_at = (payload.get("start_at") or "").strip() or now_iso()
            if not title:
                return self._json({"error": "no title"}, 400)
            return self._json(productivity.calendar_add(title, start_at))
        if self.path == "/api/knowledge":
            path = (payload.get("path") or "").strip()
            if not path:
                return self._json({"error": "no path"}, 400)
            return self._json(productivity.knowledge_add(path))
        if self.path == "/api/integrations":
            name = (payload.get("name") or "").strip()
            if not name:
                return self._json({"error": "no name"}, 400)
            return self._json(productivity.connector_enable(name, bool(payload.get("enabled", True))))
        if self.path == "/api/settings":
            return self._json(_save_settings(payload))
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
