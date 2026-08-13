import os
from pathlib import Path

import yaml

ROOT = Path(os.path.expanduser("~/aira"))
DATA = ROOT / "data"
HISTORY_DIR = DATA / "history"
AUDIO_DIR = DATA / "audio"

DEFAULTS = {
    "provider": "deepseek",
    "deepseek": {
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
    },
    "ollama": {"model": "qwen3:8b", "base_url": "http://localhost:11434/v1"},
    "slack": {
        "bot_token_env": "AIRA_SLACK_BOT_TOKEN",
        "app_token_env": "AIRA_SLACK_APP_TOKEN",
        "digest_channel": "#general",
    },
    "discord": {"webhook_env": "AIRA_DISCORD_WEBHOOK"},
    "email": {
        "enabled": False,
        "imap_host": "imap.gmail.com",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "user_env": "AIRA_EMAIL_USER",
        "pass_env": "AIRA_EMAIL_PASS",
        "poll_minutes": 5,
        "escalate_minutes": 30,
    },
    "tts": {"voice": "en-IN-NeerjaNeural", "speak_cli": True},
    "voice": {
        "poll_seconds": 2.5,
        "utterance_seconds": 10,
        "stt_model": "@cf/openai/whisper-large-v3-turbo",
        "wake_words": ["hey aira", "aira"],
    },
    "safety": {"auto": False},
    "jobs": [],
    "max_history": 40,
}


def _load_env(path=None):
    """Load ~/aira/.env into os.environ — never overriding real env vars."""
    path = Path(path or ROOT / ".env")
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _merge(base, override):
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _env_or(cfg, section, key):
    env_name = cfg.get(section, {}).get(key + "_env")
    if env_name:
        value = os.environ.get(env_name)
        if value:
            return value
    return cfg.get(section, {}).get(key)


class Config:
    def __init__(self, raw):
        self.raw = raw

    def get(self, key, default=None):
        return self.raw.get(key, default)

    def provider(self):
        return self.get("provider", "deepseek")

    def model(self):
        return self.get(self.provider(), {}).get("model", "")

    def base_url(self):
        return self.get(self.provider(), {}).get("base_url", "")

    def api_key(self):
        return _env_or(self.raw, self.provider(), "api_key") or self.get(self.provider(), {}).get("api_key", "")

    def slack_bot_token(self):
        return _env_or(self.raw, "slack", "bot_token")

    def slack_app_token(self):
        return _env_or(self.raw, "slack", "app_token")

    def discord_webhook(self):
        return _env_or(self.raw, "discord", "webhook")

    def email_user(self):
        return _env_or(self.raw, "email", "user")

    def email_pass(self):
        return _env_or(self.raw, "email", "pass")

    def tts_voice(self):
        return self.get("tts", {}).get("voice", "en-IN-NeerjaNeural")

    def digest_channel(self):
        return self.get("slack", {}).get("digest_channel", "#general")


def load_config(path=None):
    _load_env()
    path = Path(path or ROOT / "config.yaml")
    raw = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text()) or {}
    return Config(_merge(DEFAULTS, raw))
