import json
import uuid

import requests


def post_text(client, channel, text, thread_ts=None):
    if thread_ts:
        client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
    else:
        client.chat_postMessage(channel=channel, text=text)


def post_file(client, channel, path, thread_ts=None, title="Ras output"):
    try:
        if thread_ts:
            client.files_upload_v2(channels=channel, file=str(path), filename=path.name, title=title, thread_ts=thread_ts)
        else:
            client.files_upload_v2(channels=channel, file=str(path), filename=path.name, title=title)
    except Exception:
        post_text(client, channel, f"Generated file: {path}", thread_ts=thread_ts)


def post_blocks(client, channel, blocks, text="", thread_ts=None):
    kwargs = {"channel": channel, "blocks": blocks}
    if text:
        kwargs["text"] = text
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    client.chat_postMessage(**kwargs)


def approve_blocks(question):
    action_id = "ras_approve_" + uuid.uuid4().hex[:10]
    return action_id, [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":warning: *Ras needs approval*\n{question}"},
        },
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "style": "danger", "action_id": "ras_approve", "value": action_id},
                {"type": "button", "text": {"type": "plain_text", "text": "Deny"}, "action_id": "ras_deny", "value": action_id},
            ],
        },
    ]


def ack_blocks(digest_id):
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "⬆️ *Ras email digest* — press *Got it* once you have read it."},
        },
        {
            "type": "actions",
            "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Got it ✅"}, "action_id": "ras_ack", "value": digest_id}],
        },
    ]


def discord_post(webhook_url, text):
    if not webhook_url:
        return False
    try:
        resp = requests.post(webhook_url, json={"content": text}, timeout=15)
        return resp.ok
    except Exception:
        return False
