import csv
import os
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

import feedparser
from ddgs import DDGS

from . import safety, tts
from .config import DATA

MAX_OUTPUT = 6000
HOME = str(Path.home())


def clip(text, limit=MAX_OUTPUT):
    text = str(text)
    return text[:limit] + "\n...[truncated]" if len(text) > limit else text


class ToolExecutor:
    def __init__(self, session, config):
        self.session = session
        self.config = config
        self.pending = {}
        self.auto = bool(config.get("safety", {}).get("auto", False))

    def dispatch(self, tool, args, force=False):
        handler = getattr(self, tool, None)
        if handler is None:
            return {"ok": False, "error": f"Unknown tool: {tool}"}
        try:
            try:
                return handler(args, force=force)
            except TypeError:
                return handler(args)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _approve(self, key, question, force):
        if force:
            return True
        return self.session.ask_approval(key, question, force_auto=self.auto)

    def run_shell(self, args, force=False):
        command = str(args.get("command", "")).strip()
        if not command:
            return {"ok": False, "error": "empty command"}
        verdict, reason = safety.check(command, auto=self.auto)
        if verdict == "blocked":
            return {"ok": False, "error": f"BLOCKED: {reason}"}
        if verdict == "approval":
            key = f"shell_{uuid.uuid4().hex}"
            self.pending[key] = {"tool": "run_shell", "args": args}
            if not self._approve(key, f"Run this command?\n```\n{command}\n```", force):
                return {"ok": False, "error": "Denied by user."}
        cwd = os.path.expanduser(args.get("cwd") or HOME)
        timeout = int(args.get("timeout") or 120)
        env = dict(os.environ)
        env["PATH"] = f"/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:{env.get('PATH', '')}"
        try:
            proc = subprocess.run(
                f"export PATH={env['PATH']}; {command}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Command timed out after {timeout}s"}
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "output": clip(out)}

    def list_dir(self, args):
        path = Path(args.get("path") or HOME).expanduser()
        if not path.exists():
            return {"ok": False, "error": f"No such path: {path}"}
        entries = []
        for item in sorted(path.iterdir())[:200]:
            entries.append({"name": item.name, "type": "dir" if item.is_dir() else "file", "size": item.stat().st_size if item.is_file() else None})
        return {"ok": True, "path": str(path), "entries": entries}

    def read_file(self, args):
        path = Path(args.get("path")).expanduser()
        if not path.exists() or not path.is_file():
            return {"ok": False, "error": f"No such file: {path}"}
        offset = int(args.get("offset") or 0)
        limit = int(args.get("limit") or 2000)
        lines = path.read_text(errors="replace").splitlines()
        window = lines[offset:offset + limit]
        numbered = "\n".join(f"{offset + i + 1}: {line}" for i, line in enumerate(window))
        return {"ok": True, "path": str(path), "total_lines": len(lines), "content": clip(numbered, 12000)}

    def write_file(self, args, force=False):
        path = Path(args.get("path")).expanduser()
        content = str(args.get("content") or "")
        exists = path.exists()
        if exists and not args.get("overwrite"):
            key = f"write_{uuid.uuid4().hex}"
            self.pending[key] = {"tool": "write_file", "args": args}
            if not self._approve(key, f"Overwrite existing file?\n```\n{path}\n```", force):
                return {"ok": False, "error": "Denied by user."}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return {"ok": True, "path": str(path), "bytes": len(content.encode())}

    def search_files(self, args):
        path = Path(args.get("path") or HOME).expanduser()
        pattern = args.get("pattern") or "*"
        matches = []
        try:
            for item in path.rglob(pattern):
                matches.append(str(item))
                if len(matches) >= 50:
                    break
        except Exception:
            pass
        return {"ok": True, "root": str(path), "pattern": pattern, "matches": matches, "count": len(matches)}

    def open_app(self, args):
        app = args.get("app")
        if not app:
            return {"ok": False, "error": "no app name"}
        cmd = ["open", "-a", app]
        if args.get("args"):
            cmd += args["args"].split()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {"ok": proc.returncode == 0, "output": clip(proc.stdout or proc.stderr)}

    def osascript(self, args):
        script = args.get("script", "")
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
        return {"ok": proc.returncode == 0, "output": clip(proc.stdout or proc.stderr)}

    def get_time(self, args=None):
        return {"ok": True, "now": datetime.now().isoformat(timespec="seconds")}

    def web_search(self, args):
        query = args.get("query", "")
        max_results = int(args.get("max_results") or 6)
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return {"ok": True, "query": query, "results": [{"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")} for r in results]}

    def fetch_url(self, args):
        url = args.get("url", "")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read(300000).decode("utf-8", errors="replace")
        return {"ok": True, "url": url, "content": clip(body, 10000)}

    def rss_read(self, args):
        feed = feedparser.parse(args.get("url", ""))
        items = []
        for entry in feed.entries[: int(args.get("max_items") or 10)]:
            items.append({"title": entry.get("title"), "link": entry.get("link"), "published": entry.get("published", ""), "summary": clip(entry.get("summary", ""), 500)})
        return {"ok": True, "feed": args.get("url"), "items": items}

    def research_to_csv(self, args):
        topic = args.get("topic", "research")
        queries = args.get("queries")
        if isinstance(queries, str):
            queries = [queries]
        if not queries:
            return {"ok": False, "error": "no queries"}
        rows = []
        with DDGS() as ddgs:
            for query in queries:
                for r in ddgs.text(query, max_results=5):
                    rows.append([topic, query, r.get("title", ""), r.get("href", ""), r.get("body", "")])
        DATA.mkdir(parents=True, exist_ok=True)
        out = DATA / f"{topic.replace(' ', '_')}_{int(time.time())}.csv"
        with open(out, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["topic", "query", "title", "url", "snippet"])
            writer.writerows(rows)
        return {"ok": True, "path": str(out), "rows": len(rows)}

    def tts_speak(self, args):
        text = args.get("text", "")
        if not text:
            return {"ok": False, "error": "no text"}
        path = tts.generate(text, voice=self.config.tts_voice())
        self.session.post_file(path, title="Aira voice note")
        return {"ok": True, "path": str(path), "note": "audio posted to the conversation"}

    def notify(self, args):
        channel = args.get("channel") or self.config.digest_channel()
        self.session.post_text(f"*[Aira → {channel}]*\n{args.get('text', '')}", channel_override=channel)
        return {"ok": True, "channel": channel}

    def memory_add(self, args):
        from . import memory_store
        return memory_store.add_fact(args.get("text", ""), source="assistant")

    def memory_forget(self, args):
        from . import memory_store
        return memory_store.forget_fact(args.get("needle", ""))

    def learn_skill(self, args):
        from . import memory_store
        return memory_store.learn_skill(
            args.get("name", ""), args.get("description", ""), args.get("recipe", ""), tags=args.get("tags"))

    def skill_use(self, args):
        from . import memory_store
        skill = memory_store.use_skill(args.get("name", ""))
        if not skill:
            available = memory_store.list_skills()
            names = ", ".join(s["name"] for s in available) or "none"
            return {"ok": False, "error": f"no skill named '{args.get('name', '')}'. Saved skills: {names}"}
        return {"ok": True, "name": skill.get("name"), "description": skill.get("description"), "recipe": skill.get("recipe")}
