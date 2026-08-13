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
| Email gatekeeper | Gmail IMAP scan → DeepSeek triage → digest with "Got it ✅" + Discord escalation |
| Email sending | `send_email` tool (SMTP) — drafts & replies from your account |
| Calendar | `calendar_add/list/delete` tools — local store, Google-ready |
| Reminders | `reminder_add/list` — Aira surfaces due reminders automatically |
| Knowledge base | `knowledge_add/search/list` — local RAG over your own files |
| Connectors | `connectors` / `connector_enable` — pluggable app integrations |
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
├── build_popup.sh       # Siri-style overlay app (swiftc)
├── build_assistant.sh   # Aira.app mic wrapper + launchd login item
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

## Assistant mode ("Hey Aira" → Siri-style popup)

One always-on process is **both** the popup/web assistant **and** the
hands-free voice assistant, sharing a single brain + conversation. Say
**"Hey Aira"** → the Siri-style glass popup rises with the gradient orb,
it greets you aloud ("Yes, Rohit? …"), then listens for your task and
answers out loud.

Requires two one-time builds (Xcode Command Line Tools only, `swiftc`):

```bash
./build_popup.sh                              # Siri-style overlay app
./build_assistant.sh                          # mic-permission wrapper + login item
```

Then start it (or reboot — it auto-launches at login):

```bash
./venv/bin/python -m aira.main --assistant
```

- **Why `build_assistant.sh`?** macOS (TCC) only grants microphone access to
  a process running from an `.app` bundle with an `NSMicrophoneUsageDescription`.
  A bare `python -m aira.main --assistant` under launchd gets **auto-denied**,
  so the wake word silently never hears you. The script creates a tiny
  `Aira.app` whose launcher execs the assistant, and installs the
  `~/Library/LaunchAgents/com.taskveda.aira.plist` login item that runs it.
  On the first `open Aira.app`, macOS asks "Aira would like to access the
  microphone" → click **Allow**. After that it works hands-free at every login.
- **Hey Aira wake word** is fuzzy-matched by sound ("aira", "eira", "era",
  "ayra", …) so Whisper's spelling quirks don't matter. First greeting of the
  day is warm; after that, "Yes, Rohit? What do you need?".
- **Text too**: the popup and web UI (`http://localhost:8756`) share the same
  session. Destructive commands (rm, sudo, kill, overwrites) show
  **Approve / Deny** in the popup.
- **Speech**: in = ffmpeg mic → Cloudflare Workers AI Whisper; out =
  edge-tts → afplay. Cost is free-tier Cloudflare STT per clip + the brain call.
- **Troubleshooting**: mic not hearing → System Settings → Privacy & Security →
  Microphone → ensure **Aira** is enabled (not just Terminal). STT needs the
  Cloudflare Workers AI key (set `DEEPSEEK_API_KEY` / base_url in `config.yaml`).

Tune it in `config.yaml` → `voice:` (`hey_aira`, `poll_seconds`,
`utterance_seconds`, `wake_words`, `stt_model`).

## Productivity layer

Aira ships with a local-first productivity layer (`aira/productivity.py`)
that fills the big gaps vs. ChatGPT/Gemini/Lindy — all as new tools:

```bash
# Email sending (SMTP) — enable in config.yaml:
#   email.smtp_host, email.smtp_port, email.from_name
#   export AIRA_EMAIL_USER=you@gmail.com
#   export AIRA_EMAIL_PASS=<16-char app password>
# Then ask: "email Priya the meeting notes"  ->  send_email tool

# Calendar (local store, Google-ready)
#   "add a standup tomorrow 9am"          ->  calendar_add
#   "what's on my calendar this week?"    ->  calendar_list
#   "delete that event"                   ->  calendar_delete

# Reminders (auto-surfaced by the scheduler loop)
#   "remind me to call mom at 3pm"        ->  reminder_add

# Knowledge base (local RAG over your own files)
#   "index ~/Desktop/AI_Brain"            ->  knowledge_add
#   "what did I write about agents?"      ->  knowledge_search

# Connectors (pluggable integrations, see `connectors` tool)
#   gmail, google_calendar, notion, whatsapp, slack, ntfy
```

Data lives in `~/aira/data/productivity.db` (events, reminders, connectors,
indexed knowledge).
