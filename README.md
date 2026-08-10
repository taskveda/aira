# Aira

**Your own AI chief of staff — local, self-hosted, yours.**

Aira lives on your Mac, listens on **Slack**, speaks out loud, and thinks with **DeepSeek** (or a 100% free local model). It does real work on your behalf — shell commands, files, apps, web research, email digests, scheduled jobs, and voice notes — so you can ask in plain language and get results, not answers.

## Capabilities

| Area | What Aira does |
|---|---|
| Slack assistant (calendar, email, files) | Slack DM / thread frontend |
| Email gatekeeper | Gmail IMAP scan → DeepSeek triage → digest with "Got it ✅" + Discord escalation |
| Exec assistant on your laptop | Shell + file + AppleScript + browser (open) tools |
| Content research → Sheets | `research_to_csv` → CSV in `~/aira/data` |
| Scheduled workflows | cron jobs in `config.yaml` |
| Voice | Free TTS (edge-tts) audio clips posted to Slack |
| Lead calls (Vapi/Twilio, costs money) | Not included — DM outreach drafts instead |

## Requirements

- macOS, Python 3.11+ (`/usr/local/bin/python3.14` works)
- A free Slack workspace + app (5 min, steps below)
- Either a DeepSeek API key (~₹0.01–0.10 per task) **or** Ollama with a tool-calling model (100% free, e.g. `qwen3:8b`)
- Optional: Gmail app password for the email job; Discord webhook for escalation

## Setup

```bash
cd ~/aira
./setup.sh                        # creates venv + installs deps
```

### 1. Slack app (frontend)
1. Go to https://api.slack.com/apps → **Create New App** → *From scratch* → name `Aira`, pick your workspace
2. Left menu **Socket Mode** → **Enable** (generates an app-level token, `xapp-...`)
3. Left menu **OAuth & Permissions** → **Add Bot Token Scopes**: `chat:write`, `app_mentions:read`, `im:history`, `files:write`, `channels:history`
4. **Install to Workspace** → copy the **Bot User OAuth Token** (`xoxb-...`)
5. Go to your Slack workspace, DM the Aira app to open a thread

```bash
export RAS_SLACK_APP_TOKEN=xapp-...
export RAS_SLACK_BOT_TOKEN=xoxb-...
```

### 2. Brain — pick one

DeepSeek (recommended): get a key at https://platform.deepseek.com
```bash
export DEEPSEEK_API_KEY=sk-...
# config.yaml -> provider: deepseek (default)
```

Ollama (100% free, runs on your Mac):
```bash
brew install ollama
ollama pull qwen3:8b
# config.yaml -> provider: ollama
```
Note: pick a tool-calling model (`qwen3`, `llama3.1+`). `deepseek-r1` distill models are chat-only; Aira falls back to JSON mode with them.

### 3. Email digest (optional)
1. Enable 2FA on your Google account → https://myaccount.google.com/apppasswords → generate one
2. Edit `config.yaml`: `email.enabled: true`, keep `imap_host: imap.gmail.com`
3. `export RAS_EMAIL_USER=you@gmail.com` and `export RAS_EMAIL_PASS=<16-char app password>`

### 4. Discord escalation (optional)
Create a Discord server → Server Settings → Integrations → **Webhooks** → New Webhook → copy URL → `export RAS_DISCORD_WEBHOOK=...`

## Run

```bash
# 0. NO-ACCOUNT web frontend (works immediately — recommended to start):
./venv/bin/python -m aira.main --web
#   opens http://localhost:8756 in your browser — chat, approvals, history

# 1. Test the brain without Slack (recommended first):
./venv/bin/python -m aira.main --cli

# 2. Live on Slack (needs the Slack app from the setup steps above):
./venv/bin/python -m aira.main
```

One-shot mode for scripts: `./venv/bin/python -m aira.main --once "summarize my downloads folder"`

## Content automation

Aira has scheduled content jobs (see `config.yaml` → `jobs`, `type: automation`)
for your daily content engine. Run any of them manually:

```bash
./venv/bin/python -m aira.main --automate carousel   # Instagram carousel plan -> ~/Instagram_Content
./venv/bin/python -m aira.main --automate linkedin   # LinkedIn post -> ~/LinkedIn_Content
./venv/bin/python -m aira.main --automate briefing   # daily AI briefing + ntfy phone push
./venv/bin/python -m aira.main --automate blog --count 2   # 2 SEO/AEO/GEO posts -> blog repo + git push
```

- **carousel** — writes the next `NNN_Daily_Content/` folder with
  `Carousel_Plan.md` (3 fresh topics) + one full 10-slide plan + image prompts
  per topic. Uses shared memory + guard rules so topics never repeat.
- **linkedin** — one daily, Vaibhav-style news→meaning→lesson→question post.
- **briefing** — reuses `~/rohit-daily-briefing/research.py` (no LLM), then
  pushes a summary to your phone via ntfy.
- **blog** — writes `n` production SEO/AEO/GEO + LLM-optimized posts (JSON-LD,
  canonical, speakable, FAQ, sourced facts) into
  `~/Dev/taskveda-z2c-blog/blog/<slug>/index.html`, then **commits + pushes**
  to the blog git repo. Fully automated — no review step.

All four log their result to the shared memory system
(`~/ai-daily-automation/shared/memory.py`) so past topics and facts are consistent.

Scheduled (in `config.yaml` by default): carousel Mon–Sat 8 PM, LinkedIn daily
9 AM, briefing 8:30 AM, and blog posts Mon/Wed/Fri (2 each ≈ 6/week).


## Example commands (DM Aira in Slack)

- "find the largest file in ~/Downloads"
- "check my inbox and tell me what's urgent" (only if email enabled — otherwise it tells you it can't)
- "research AI agent platforms and save to CSV"
- "open Safari and fetch https://growthschool.io — summarize it"
- "read this project's README and give me a 5-line summary"
- "speak 'remind me to call mom tomorrow' as audio"
- "every morning at 9am" (configured via `jobs` in `config.yaml`)

## Safety model

- **Auto**: safe ops run immediately (read, search, research, drafts, summaries)
- **Ask**: destructive/system-affecting commands (`rm`, `sudo`, `kill`, overwrites…) pause and post **Approve / Deny** buttons in Slack
- **Blocked**: catastrophic commands (`rm -rf /`, disk wipe) are refused outright
- Set `safety.auto: true` in `config.yaml` to disable asking (not recommended)

## Files

```
~/aira/
├── config.yaml          # all settings
├── requirements.txt
├── setup.sh
├── aira/
│   ├── main.py          # entry point
│   ├── brain.py         # DeepSeek/Ollama tool-calling loop
│   ├── executor.py      # shell/files/apps/web/sheets/tts tools
│   ├── webui.py         # local browser frontend (no accounts needed)
│   ├── slack_bot.py     # Socket Mode listener + approval buttons
│   ├── email_watcher.py # IMAP scan → digest → Discord escalation
│   ├── scheduler.py     # cron jobs
│   ├── safety.py        # approval rules
│   ├── notifier.py      # Slack/Discord posting
│   ├── tts.py           # edge-tts voice notes
│   └── cli.py           # terminal mode (no Slack)
└── data/                # CSVs, history, audio

## Voice mode ("Hey Aira")

Hands-free, spoken Aira. Zero extra installs — it uses ffmpeg (mic) +
Cloudflare Workers AI Whisper (speech-to-text, same account/key as the
brain) + edge-tts (speech out).

```bash
./venv/bin/python -m aira.main --voice
```

- Say **"Hey Aira"** to wake it, then say your task. It answers out loud.
- One greeting per day; after that, straight to work.
- Destructive commands (rm, sudo, kill, overwrites) pause and Aira asks
  you out loud — answer "yes" or "no".
- First run: macOS will ask for **microphone access** for your terminal.
  If it fails, check System Settings → Privacy & Security → Microphone.
- Cost: whisper is free-tier Cloudflare (~2.5s poll clips); each spoken
  exchange is one or two STT calls + the brain call.

Tune it in `config.yaml` → `voice:` (poll_seconds, utterance_seconds,
wake_words, stt_model).

## Siri-style popup

A native macOS overlay, like Siri: press **Option+Space** (or the menu-bar
icon) and a floating glass panel appears — tap the mic and talk, or just
type. Aira runs the same agentic brain (tools, research, files, shell) and
answers in chat bubbles, speaking the reply aloud.

```bash
./build_popup.sh                              # one-time build (Xcode CLT: swiftc)
./venv/bin/python -m aira.main --popup         # starts the API server + opens the popup
```

- Destructive commands show **Approve / Deny** buttons right in the popup.
- Speech-to-text uses the same free Cloudflare Whisper; voice-out is
  edge-tts played via afplay.
- Mic permission: the app is already signed ad-hoc; grant access when
  macOS asks, or via System Settings → Privacy & Security → Microphone.
```
