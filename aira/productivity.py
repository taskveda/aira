"""Aira productivity layer: email sending, calendar, reminders, a local
knowledge base (RAG), and a pluggable connector registry.

Design goals:
- Local-first: everything works with zero cloud accounts where possible.
- Config-driven credentials: read from ~/aira/.env / config.yaml via the
  existing Config helper; never hardcode secrets.
- Tools surface cleanly in the executor + brain TOOLS list.
"""

import json
import smtplib
import sqlite3
import threading
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from .config import DATA, ROOT

DB_PATH = DATA / "productivity.db"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_lock = threading.Lock()


def _connect():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init():
    with _lock:
        conn = _connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                start_at TEXT NOT NULL,      -- ISO 8601 local
                end_at TEXT,
                location TEXT,
                notes TEXT,
                source TEXT DEFAULT 'local'
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                due_at TEXT NOT NULL,        -- ISO 8601 local
                done INTEGER DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS connectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                enabled INTEGER DEFAULT 0,
                meta TEXT
            );
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                path TEXT,
                content TEXT,
                updated_at TEXT
            );
            """
        )
        conn.commit()
        conn.close()


_init()


# ---------------------------------------------------------------------------
# Email sending (SMTP)
# ---------------------------------------------------------------------------

def send_email(config, to, subject, body, cc=None, bcc=None, html=None):
    """Send an email via SMTP using the configured account.

    Returns a dict with ok/error. Needs email.user + email.pass (app password)
    and email.smtp_host / smtp_port in config.yaml or .env.
    """
    host = config.get("email", {}).get("smtp_host") or "smtp.gmail.com"
    port = int(config.get("email", {}).get("smtp_port") or 587)
    user = config.email_user()
    password = config.email_pass()
    from_name = config.get("email", {}).get("from_name") or "Rohit (via Aira)"

    if not user or not password:
        return {"ok": False, "error": "email not configured — set email.user, email.pass, email.smtp_host in config.yaml/.env"}

    if isinstance(to, str):
        to = [t.strip() for t in to.split(",") if t.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, user))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc
    if bcc:
        msg["Bcc"] = ", ".join(bcc) if isinstance(bcc, list) else bcc
    if html:
        msg.set_content(body or "")
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.send_message(msg)
        return {"ok": True, "to": to, "subject": subject}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Calendar (local store, Google-ready)
# ---------------------------------------------------------------------------

def calendar_add(title, start_at, end_at=None, location="", notes=""):
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO events (title, start_at, end_at, location, notes) VALUES (?,?,?,?,?)",
            (title, start_at, end_at, location, notes),
        )
        conn.commit()
        eid = cur.lastrowid
        conn.close()
    return {"ok": True, "id": eid, "title": title, "start_at": start_at}


def calendar_list(day=None, days_ahead=7):
    """List events. day = 'YYYY-MM-DD' filters to that day; else next N days."""
    with _lock:
        conn = _connect()
        if day:
            start = f"{day}T00:00:00"
            end = f"{day}T23:59:59"
            rows = conn.execute(
                "SELECT * FROM events WHERE start_at BETWEEN ? AND ? ORDER BY start_at", (start, end)
            ).fetchall()
        else:
            start = datetime.now().isoformat(timespec="seconds")
            end = (datetime.now() + timedelta(days=days_ahead)).isoformat(timespec="seconds")
            rows = conn.execute(
                "SELECT * FROM events WHERE start_at BETWEEN ? AND ? ORDER BY start_at", (start, end)
            ).fetchall()
        conn.close()
    return {"ok": True, "count": len(rows), "events": [dict(r) for r in rows]}


def calendar_delete(event_id):
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        conn.commit()
        conn.close()
    return {"ok": True, "deleted_id": event_id}


# ---------------------------------------------------------------------------
# Reminders (natural-language friendly, persisted)
# ---------------------------------------------------------------------------

def reminder_add(text, due_at):
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO reminders (text, due_at, created_at) VALUES (?,?,?)",
            (text, due_at, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        rid = cur.lastrowid
        conn.close()
    return {"ok": True, "id": rid, "text": text, "due_at": due_at}


def reminder_due(now=None):
    """Return reminders that are due but not yet done, and mark them done."""
    now = now or datetime.now().isoformat(timespec="seconds")
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM reminders WHERE due_at <= ? AND done=0 ORDER BY due_at", (now,)
        ).fetchall()
        for r in rows:
            conn.execute("UPDATE reminders SET done=1 WHERE id=?", (r["id"],))
        conn.commit()
        conn.close()
    return [dict(r) for r in rows]


def reminder_list(include_done=False):
    with _lock:
        conn = _connect()
        if include_done:
            rows = conn.execute("SELECT * FROM reminders ORDER BY due_at").fetchall()
        else:
            rows = conn.execute("SELECT * FROM reminders WHERE done=0 ORDER BY due_at").fetchall()
        conn.close()
    return [dict(r) for r in rows]


def reminder_done(reminder_id):
    """Mark a single reminder as done. Returns the updated record or None."""
    with _lock:
        conn = _connect()
        cur = conn.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Knowledge base (local RAG — keyword index over your files)
# ---------------------------------------------------------------------------

def _tokenize(text):
    import re
    return re.findall(r"[a-z0-9]{3,}", text.lower())


def _index_file(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        content = path.read_text(errors="ignore")
    except Exception:
        return None
    title = path.name
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO knowledge (title, path, content, updated_at) VALUES (?,?,?,?)",
            (title, str(path), content[:200000], datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        conn.close()
    return {"title": title, "path": str(path), "chars": len(content)}


def knowledge_add(paths):
    """Index one or more file paths into the local knowledge base."""
    if isinstance(paths, str):
        paths = [paths]
    results = []
    for p in paths:
        res = _index_file(p)
        if res:
            results.append(res)
    return {"ok": True, "indexed": results, "count": len(results)}


def knowledge_search(query, limit=5):
    """Simple keyword retrieval over indexed content (local RAG without deps)."""
    query = _tokenize(query)
    if not query:
        return {"ok": False, "error": "empty query"}
    with _lock:
        conn = _connect()
        rows = conn.execute("SELECT * FROM knowledge").fetchall()
        conn.close()
    scored = []
    for row in rows:
        content = row["content"]
        tokens = _tokenize(content)
        score = sum(tokens.count(q) for q in query)
        if score:
            # find first snippet window
            low = content.lower()
            idx = min([low.find(q) for q in query if q in low] or [0])
            snippet = content[max(0, idx - 100): idx + 400].replace("\n", " ")
            scored.append({"score": score, "title": row["title"], "path": row["path"], "snippet": snippet})
    scored.sort(key=lambda r: -r["score"])
    return {"ok": True, "results": scored[:limit], "count": len(scored[:limit])}


def knowledge_list():
    with _lock:
        conn = _connect()
        rows = conn.execute("SELECT id,title,path,updated_at FROM knowledge ORDER BY updated_at DESC").fetchall()
        conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Connector registry
# ---------------------------------------------------------------------------

KNOWN_CONNECTORS = {
    "gmail": "Send + read email (SMTP/IMAP) — set email.* in config",
    "google_calendar": "Calendar read/create via Google Calendar API",
    "notion": "Docs + databases via Notion API",
    "whatsapp": "WhatsApp messaging (Twilio or local)",
    "slack": "Slack channels (built in)",
    "ntfy": "Phone push notifications (built in)",
}


def connector_status():
    with _lock:
        conn = _connect()
        rows = conn.execute("SELECT name, enabled, meta FROM connectors").fetchall()
        conn.close()
    known = {k: {"enabled": False, "description": v} for k, v in KNOWN_CONNECTORS.items()}
    for r in rows:
        if r["name"] in known:
            known[r["name"]]["enabled"] = bool(r["enabled"])
    return {"ok": True, "connectors": known}


def connector_enable(name, enabled=True):
    if name not in KNOWN_CONNECTORS:
        return {"ok": False, "error": f"unknown connector '{name}'. Known: {', '.join(KNOWN_CONNECTORS)}"}
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO connectors (name, enabled) VALUES (?,?) "
            "ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled",
            (name, int(bool(enabled))),
        )
        conn.commit()
        conn.close()
    return {"ok": True, "name": name, "enabled": bool(enabled)}
