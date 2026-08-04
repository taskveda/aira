import json
import threading
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from . import notifier
from .brain import Brain
from .config import HISTORY_DIR
from .executor import ToolExecutor


class SlackSession:
    def __init__(self, client, channel, thread_ts):
        self.client = client
        self.channel = channel
        self.thread_ts = thread_ts
        self.resolvers = {}

    def post_text(self, text, channel_override=None):
        notifier.post_text(self.client, channel_override or self.channel, text, thread_ts=self.thread_ts)

    def post_file(self, path, title="Ras output"):
        notifier.post_file(self.client, self.channel, path, thread_ts=self.thread_ts, title=title)

    def ask_approval(self, question, force_auto=False):
        if force_auto:
            return True
        aid, blocks = notifier.approve_blocks(question)
        event = threading.Event()
        self.resolvers[aid] = event
        notifier.post_blocks(self.client, self.channel, blocks, text="Ras needs approval", thread_ts=self.thread_ts)
        answered = event.wait(timeout=600)
        self.resolvers.pop(aid, None)
        return answered and getattr(event, "approved", False)

    def resolve(self, action_id, approved):
        event = self.resolvers.get(action_id)
        if event:
            event.approved = approved
            event.set()


def history_file(channel, thread_ts):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    name = (channel + "_" + (thread_ts or "")).replace(".", "_").replace("#", "")
    return HISTORY_DIR / f"{name}.json"


def load_history(channel, thread_ts, limit=20):
    path = history_file(channel, thread_ts)
    if path.exists():
        try:
            return json.loads(path.read_text())[-limit:]
        except Exception:
            return []
    return []


def save_history(channel, thread_ts, messages, limit=20):
    path = history_file(channel, thread_ts)
    path.write_text(json.dumps(messages[-limit:]))


def create_bot(config, brain_factory=None):
    app = App(token=config.slack_bot_token())
    executor_holder = {"executor": None}

    def make_session(client, channel, thread_ts):
        return SlackSession(client, channel, thread_ts)

    @app.event("message")
    @app.event("app_mention")
    def handle(event, say, client):
        if event.get("subtype") == "bot_message":
            return
        channel_type = event.get("channel_type") or ""
        text = (event.get("text") or "").strip()
        if not text:
            return
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event.get("ts")
        if channel_type != "im" and not event.get("thread_ts") and not event.get("type") == "app_mention":
            return
        if channel_type == "im" or event.get("type") == "app_mention" or event.get("thread_ts"):
            threading.Thread(target=run_task, args=(client, channel, thread_ts, text), daemon=True).start()

    def run_task(client, channel, thread_ts, text):
        try:
            session = make_session(client, channel, thread_ts)
            executor = ToolExecutor(session, config)
            executor_holder["executor"] = executor
            brain = brain_factory(executor) if brain_factory else Brain(config, executor)
            history = load_history(channel, thread_ts)
            history.append({"role": "user", "content": text})
            reply = brain.run(history)
            history.append({"role": "assistant", "content": reply})
            save_history(channel, thread_ts, history)
            session.post_text(reply)
        except Exception as exc:
            try:
                notifier.post_text(client, channel, f"Ras hit an error: {type(exc).__name__}: {exc}", thread_ts=thread_ts)
            except Exception:
                pass

    @app.action("ras_approve")
    def on_approve(ack, body, client):
        ack()
        action_id = body["actions"][0]["value"]
        session = _session_for(body, client)
        if session:
            session.resolve(action_id, True)

    @app.action("ras_deny")
    def on_deny(ack, body, client):
        ack()
        action_id = body["actions"][0]["value"]
        session = _session_for(body, client)
        if session:
            session.resolve(action_id, False)

    @app.action("ras_ack")
    def on_ack(ack, body, client):
        ack()
        digest_id = body["actions"][0]["value"]
        holder = getattr(app, "_ras_ack_handler", None)
        if holder:
            holder(digest_id)

    sessions = {}

    def _session_for(body, client):
        channel = body.get("channel", {}).get("id")
        message = body.get("message", {})
        thread_ts = message.get("thread_ts") or message.get("ts")
        if not channel:
            return None
        key = (channel, thread_ts)
        if key not in sessions:
            sessions[key] = make_session(client, channel, thread_ts)
        return sessions[key]

    app._ras_ack_handler = None
    return app, executor_holder


def start(config, brain_factory=None):
    app, holder = create_bot(config, brain_factory)
    handler = SocketModeHandler(app, config.slack_app_token())
    return app, holder, handler
