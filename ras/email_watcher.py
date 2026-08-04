import email
import imaplib
import json
import re
import threading
import time
import uuid
from email.header import decode_header
from pathlib import Path

from . import notifier
from .brain import Brain
from .config import DATA

TRIAGE_PROMPT = """You are Ras, an email assistant. Analyze the JSON list of emails below and reply with ONLY a JSON array.
For each email output: {"id": n, "from": "...", "subject": "...", "urgent": 0-5, "category": "personal|work|newsletter|promo|other", "summary": "one sentence", "suggested_reply": "one sentence draft or empty string if no reply needed"}.
Sort by urgent descending. Never invent emails that are not in the input."""


def _decode(value):
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            out.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _snippet(body_text, limit=500):
    text = re.sub(r"<[^>]+>", " ", body_text)
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


class EmailWatcher:
    def __init__(self, config, brain_factory, post_client=None):
        self.config = config
        self.brain_factory = brain_factory
        self.post_client = post_client
        self.acked = set()
        self.seen_file = DATA / "seen_uids.txt"
        self._seen = self._load_seen()
        self._running = True

    def _load_seen(self):
        if self.seen_file.exists():
            return set(self.seen_file.read_text().split())
        return set()

    def _save_seen(self):
        self.seen_file.write_text("\n".join(sorted(self._seen)))

    def scan(self):
        email_cfg = self.config.get("email", {})
        host = email_cfg.get("imap_host", "imap.gmail.com")
        user = self.config.email_user()
        password = self.config.email_pass()
        if not user or not password:
            return []
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        mail.select("INBOX")
        _, data = mail.search(None, "UNSEEN")
        uids = data[0].split() if data and data[0] else []
        found = []
        for uid in uids:
            uid_str = uid.decode()
            if uid_str in self._seen:
                continue
            _, msg_data = mail.fetch(uid, "(RFC822)")
            raw = msg_data[0][1] if msg_data and msg_data[0] else None
            if not raw:
                continue
            message = email.message_from_bytes(raw)
            body_text = ""
            if message.is_multipart():
                for part in message.walk():
                    if part.get_content_type() == "text/plain":
                        body_text = part.get_payload(decode=True).decode(errors="replace")
                        break
            else:
                payload = message.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(errors="replace")
            found.append({
                "id": uid_str,
                "from": _decode(message.get("From")),
                "subject": _decode(message.get("Subject")) or "(no subject)",
                "date": message.get("Date", ""),
                "snippet": _snippet(body_text),
            })
        mail.logout()
        for item in found:
            self._seen.add(item["id"])
        self._save_seen()
        return found

    def triage_and_post(self):
        emails = self.scan()
        if not emails:
            return
        brain = self.brain_factory(None)
        content = brain.complete(
            [{"role": "system", "content": TRIAGE_PROMPT}, {"role": "user", "content": json.dumps(emails[:30])}],
            json_mode=True,
            temperature=0.1,
        )
        items = self._parse_array(content)
        if not items:
            items = [{"id": e["id"], "from": e["from"], "subject": e["subject"], "urgent": 1, "category": "other", "summary": e["snippet"][:200], "suggested_reply": ""} for e in emails[:10]]
        digest_id = uuid.uuid4().hex[:12]
        lines = [f"*Ras digest — {len(items)} new email(s)*"]
        for item in items[:12]:
            flags = "🔥" if int(item.get("urgent", 0)) >= 4 else "·"
            lines.append(f"{flags} *{item.get('subject', '')[:120]}*\n    from {item.get('from', '')[:80]} — {item.get('summary', '')[:220]}")
            if item.get("suggested_reply"):
                lines.append(f"    💬 draft reply: {item['suggested_reply'][:200]}")
        text = "\n".join(lines)
        self._post_digest(text, digest_id)

    def _post_digest(self, text, digest_id):
        channel = self.config.digest_channel()
        if self.post_client:
            notifier.post_text(self.post_client, channel, text)
            notifier.post_blocks(self.post_client, channel, notifier.ack_blocks(digest_id), text="Digest — mark as read")
        else:
            print(text)
        self.acked.add(digest_id)
        escalate_min = int(self.config.get("email", {}).get("escalate_minutes", 30))
        threading.Timer(escalate_min * 60, self._escalate, args=(digest_id, text)).start()

    def _escalate(self, digest_id, text):
        if digest_id in self.acked:
            return
        webhook = self.config.discord_webhook()
        ok = notifier.discord_post(webhook, f"[ESCALATED — unread digest] {text}") if webhook else False
        if ok and self.post_client:
            notifier.post_text(self.post_client, self.config.digest_channel(), "Digest still unread — escalated to Discord.")

    def _parse_array(self, content):
        try:
            start, end = content.find("["), content.rfind("]")
            if start == -1 or end == -1:
                return []
            return json.loads(content[start:end + 1])
        except Exception:
            return []

    def run(self):
        poll_min = int(self.config.get("email", {}).get("poll_minutes", 5))
        while self._running:
            try:
                self.triage_and_post()
            except Exception as exc:
                print(f"[ras] email scan error: {exc}")
            for _ in range(poll_min * 60):
                time.sleep(1)
                if not self._running:
                    return
