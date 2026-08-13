import json
import re
import urllib.request

from openai import OpenAI

SYSTEM_PROMPT = """You are AIRA — Rohit's personal AI employee, the voice assistant living on his Mac. You speak, you act, you don't waste words. Modeled on Vaibhav Sisinty's Jerry: you run his life — emails, calls, calendar, content, brand deals — and you bring him decisions, never homework.

WHO HE IS:
Rohit, 21, founder/CEO of TaskVeda — AI skills + internships for Indian tier-2/3 students. 3,500+ students, WhatsApp community, daily LinkedIn and Instagram content, brand deals coming in. Your best friend AND boss.

YOUR FIVE DOMAINS (own them):
1. EMAIL — triage his inbox: kill spam, draft replies in his voice, escalate only what needs his eyes. Digest, not dump.
2. CALLS — draft scripts, decide what he must take vs handle by message.
3. CALENDAR — his grid (11_Reach_System.md): LinkedIn 9 AM, Instagram 8 PM. Never let him miss.
4. CONTENT — LinkedIn posts, Instagram carousels, PDFs. Hook in 2 lines, real numbers, no AI tells, no links in body — replies only.
5. BRAND DEALS — spot inbound money, draft outreach + negotiation replies. Every opportunity = a short note + a draft.

THE JERRY ATTITUDE:
- "I'll handle it. You approve." Default = DO the work. Come back with the finished thing and a one-line summary. Never ask "what should I do?" — propose, then do.
- Bring decisions, not tasks: 2-3 sharp options ONLY when it's truly his call (money, reputation, his words).
- Proactive: if a task implies a follow-up, do it or flag it in one line.
- See an opportunity? "💡 Idea: ..." once per task. Specific, never generic.

HOW TO WORK:
1. THINK → PLAN (2-6 tool calls) → ACT (read results before next call) → VERIFY (re-read files/shell) → DELIVER (what you did, where it's saved).
2. Research: his files first (~/LinkedIn_Content, ~/Desktop/AI_Brain, ~/aira/data), then web (search → fetch top sources → extract). Never answer from memory when tools exist.
3. Retry a failed search once, then report honestly.

TOOLS: run_shell, list_dir, read_file, write_file, search_files, open_app, osascript, get_time, web_search, fetch_url, rss_read, research_to_csv, tts_speak, notify.

SAFETY: safe actions run immediately. Destructive/system-changing (rm, sudo, kill, overwrite, outside home) — pause, ask approval. Never claim work you didn't do; report exact errors.

VOICE MODE (you are spoken, not typed):
- Answers under 3 sentences when possible. One sentence when it works.
- Finish with one clear next action if there is one. No filler words, no "as an AI", no hedging.
- Numbers and names: say them simply so they're easy to hear.
- If he's angry or rushed: match him — short, done, next.
- Greeting (first time each day): "Yo, I'm Aira. What are we building today?" After that, no greetings — straight to work.

MEMORY & LEARNING (Letta-style, you CAN edit your own memory):
- You have a persistent memory block injected above. Use it, don't re-ask.
- Important new durable facts (preferences, projects, constraints) → call memory_add.
- To stop remembering something → memory_forget.
- When you discover a reusable multi-step recipe after doing a real task, save it with learn_skill(name, description, recipe) so next time is one step, not ten.
- If the current task matches a saved skill (listed above, or auto-injected as ACTIVE SKILL), call skill_use(name) first — load the recipe and follow it. Reuse, don't reinvent.
- Never invent memory content. Only store what you actually did or were told."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run any shell command on the user's Mac (zsh/sh). Destructive commands automatically require user approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run, e.g. 'ls -la ~/Downloads'"},
                    "cwd": {"type": "string", "description": "Working directory (default: home)"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and folders in a directory.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file with optional line offset/limit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or create a file. Overwriting an existing file requires approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean", "description": "Set true to force-overwrite (triggers approval)"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for files by glob pattern under a path, e.g. pattern '**/*.pdf'.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}}, "required": ["pattern"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open an application on the Mac, e.g. open_app(app='Safari', args='https://...').",
            "parameters": {"type": "object", "properties": {"app": {"type": "string"}, "args": {"type": "string"}}, "required": ["app"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osascript",
            "description": "Run an AppleScript to control Mac apps (e.g. tell app Safari to ...).",
            "parameters": {"type": "object", "properties": {"script": {"type": "string"}}, "required": ["script"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web (DuckDuckGo).",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch the text content of a web page.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rss_read",
            "description": "Read latest items from an RSS/Atom feed.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}, "max_items": {"type": "integer"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_to_csv",
            "description": "Run several web searches and write the results to a CSV in ~/aira/data. Use for research tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "queries": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["topic", "queries"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tts_speak",
            "description": "Speak text aloud: generates a free TTS audio clip and posts it to the conversation.",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify",
            "description": "Post a message to a Slack channel.",
            "parameters": {"type": "object", "properties": {"channel": {"type": "string"}, "text": {"type": "string"}}, "required": ["text"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get the current date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_add",
            "description": "Remember a durable fact about Rohit or the work (project state, preferences, decisions). Stored permanently and injected into context on future tasks.",
            "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "The fact to remember, one clean sentence."}}, "required": ["text"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_forget",
            "description": "Stop remembering any stored facts containing the given text.",
            "parameters": {"type": "object", "properties": {"needle": {"type": "string"}}, "required": ["needle"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_skill",
            "description": "Save a reusable multi-step recipe you just did well, so future tasks reuse it instead of rebuilding from scratch. Call with a short name, a one-line description, and the copy-pasteable recipe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "recipe": {"type": "string", "description": "The step-by-step recipe/value-adding play"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "description", "recipe"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_use",
            "description": "Load a saved skill/recipe into context and mark it used. Call FIRST when the current task matches a learned skill — reuse the recipe, don't reinvent it.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Skill name to load, e.g. 'LinkedIn Hooks'"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email (SMTP) from Rohit's configured account. Use for drafts/replies/outreach. Returns ok/error if not configured.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email(s), comma-separated"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "cc": {"type": "string"},
                    "bcc": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_add",
            "description": "Add an event to Aira's calendar. start_at/end_at in ISO 8601 local time, e.g. '2026-08-14T18:00:00'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_at": {"type": "string"},
                    "end_at": {"type": "string"},
                    "location": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["title", "start_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_list",
            "description": "List calendar events. Use day='YYYY-MM-DD' for one day, or days_ahead for the next N days (default 7).",
            "parameters": {
                "type": "object",
                "properties": {"day": {"type": "string"}, "days_ahead": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_delete",
            "description": "Delete a calendar event by its id.",
            "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reminder_add",
            "description": "Set a reminder. due_at in ISO 8601 local time, e.g. '2026-08-14T15:00:00'. Aira will surface it when due.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "due_at": {"type": "string"}},
                "required": ["text", "due_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reminder_list",
            "description": "List pending reminders.",
            "parameters": {"type": "object", "properties": {"include_done": {"type": "boolean"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_add",
            "description": "Index one or more file paths (list of strings) into Aira's local knowledge base so it can answer from your own documents.",
            "parameters": {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}}, "required": ["paths"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": "Search Aira's indexed local knowledge base for a query. Use before answering from 'your' documents.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_list",
            "description": "List documents currently in the local knowledge base.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "connectors",
            "description": "List available external connectors (gmail, google_calendar, notion, whatsapp, slack, ntfy) and whether each is enabled.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "connector_enable",
            "description": "Enable or disable a connector. Name from the connectors list, e.g. gmail, notion.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "enabled": {"type": "boolean"}},
                "required": ["name"],
            },
        },
    },
]

JSON_FALLBACK = """You are Aira, a personal AI assistant with full laptop access.
Respond ONLY with valid JSON, either:
{"tool": "name", "args": {...}}  to call a tool
or {"reply": "text"}  to answer directly.
Available tools: run_shell, list_dir, read_file, write_file, search_files, open_app, osascript, web_search, fetch_url, rss_read, research_to_csv, tts_speak, notify, get_time, memory_add, memory_forget, learn_skill, skill_use, send_email, calendar_add, calendar_list, calendar_delete, reminder_add, reminder_list, knowledge_add, knowledge_search, knowledge_list, connectors, connector_enable."""


def _clean(content):
    import re
    cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    if "<think" in cleaned:
        cleaned = cleaned.split("<think", 1)[0].strip()
    return cleaned


class OllamaClient:
    def __init__(self, base_url, model):
        self.base_url = base_url.rstrip("/").replace("/v1", "")
        self.model = model

    def _post(self, body, timeout=600):
        req = urllib.request.Request(
            self.base_url + "/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def chat(self, messages, tools=None, temperature=0.4, json_mode=False):
        body = {
            "model": self.model,
            "think": False,
            "stream": False,
            "messages": messages,
            "options": {"temperature": temperature},
        }
        if tools:
            body["tools"] = tools
        if json_mode:
            body["format"] = "json"
        data = self._post(body)
        message = data.get("message", {})
        content = message.get("content") or ""
        calls = message.get("tool_calls") or []
        return content, calls


def _persona():
    """Optional memory strap (who Rohit is, how he writes, what's live) so Aira
    feels like the same assistant in every mode — text, voice, popup, Slack."""
    try:
        from .memory import strap
        return strap()
    except Exception:
        return ""


class Brain:
    def __init__(self, config, executor):
        self.config = config
        self.executor = executor
        self.model = config.model()
        if config.provider() == "ollama":
            self.client = None
            self.ollama = OllamaClient(config.base_url(), config.model())
        else:
            self.client = OpenAI(base_url=config.base_url(), api_key=config.api_key() or "none")
            self.ollama = None
        self.tool_supported = True

    def complete(self, messages, json_mode=False, temperature=0.4):
        if self.ollama:
            content, _ = self.ollama.chat(messages, tools=None, temperature=temperature, json_mode=json_mode)
            return _clean(content)
        kwargs = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": 2048}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        return _clean(resp.choices[0].message.content or "")

    def run(self, messages, max_iters=10):
        persona = _persona()
        extra = ""
        try:
            from .memory_store import bundle, skill_trigger
            user_txt = " ".join(m.get("content", "") for m in messages if m.get("role") == "user")
            mem = bundle()
            if mem:
                extra = f"\n\n--- AIRA'S PERSISTENT MEMORY (you can edit via tools) ---\n{mem}"
            trigger = skill_trigger(user_txt)
            if trigger:
                extra += trigger
        except Exception:
            pass
        system = SYSTEM_PROMPT + (f"\n\n--- ROHIT'S LIVE CONTEXT (read only, local) ---\n{persona}" if persona else "") + extra
        msgs = [{"role": "system", "content": system}] + messages
        last_call = None
        repeat = 0
        reply = ""
        try:
            reply = self._run_loop(msgs, max_iters, last_call, repeat)
            self._maybe_learn(messages, msgs)
            return reply
        finally:
            try:
                from .memory_store import auto_remember
                user_txt = " ".join(m.get("content", "") for m in messages if m.get("role") == "user")
                auto_remember(user_txt, str(reply))
            except Exception:
                pass

    def _run_loop(self, msgs, max_iters, last_call, repeat):
        for _ in range(max_iters):
            if self.ollama:
                content, calls = self.ollama.chat(msgs, tools=TOOLS)
                if content:
                    parsed = _parse_json_tool(content)
                    if parsed:
                        result = self.executor.dispatch(parsed.get("name"), parsed.get("arguments") or {})
                        msgs.append({"role": "user", "content": f"Tool {parsed.get('name')} returned: " + json.dumps(result, default=str)[:12000]})
                        continue
                    msgs.append({"role": "assistant", "content": content})
                return _clean(content)
                if not calls:
                    return "I could not generate a response. The local model may need retuning — try DeepSeek."
                msgs.append({"role": "assistant", "content": content, "tool_calls": calls})
                for call in calls:
                    fn = call.get("function", {})
                    name = fn.get("name")
                    raw_args = fn.get("arguments") or {}
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            args = {}
                    else:
                        args = raw_args
                    result = self.executor.dispatch(name, args)
                    msgs.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(result, default=str)[:12000]})
                continue
            if self.tool_supported:
                try:
                    resp = self.client.chat.completions.create(model=self.model, messages=msgs, tools=TOOLS, temperature=0.4, max_tokens=2048)
                except Exception:
                    self.tool_supported = False
                    continue
                msg = resp.choices[0].message
                if msg.tool_calls:
                    msgs.append({
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {"id": c.id, "type": "function",
                             "function": {"name": c.function.name, "arguments": c.function.arguments or ""}}
                            for c in msg.tool_calls
                        ],
                    })
                    calls = []
                    for call in msg.tool_calls:
                        try:
                            args = json.loads(call.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {"command": call.function.arguments or ""}
                        key = (call.function.name, str(sorted(args.items())))
                        if key == last_call:
                            repeat += 1
                        else:
                            repeat = 0
                        last_call = key
                        calls.append((call, args))
                    if repeat >= 2:
                        self.tool_supported = False
                        continue
                    for call, args in calls:
                        result = self.executor.dispatch(call.function.name, args)
                        msgs.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)[:12000]})
                    continue
                content = msg.content or ""
                parsed = _parse_json_tool(content)
                if parsed:
                    result = self.executor.dispatch(parsed.get("name"), parsed.get("arguments") or {})
                    msgs.append({"role": "user", "content": f"Tool {parsed.get('name')} returned: " + json.dumps(result, default=str)[:12000]})
                    continue
                if any(k in content.lower() for k in ("more detail", "please clarify", "incomplete", "provide more", "could you please")):
                    msgs.append({"role": "user", "content": "Stop asking for clarification. Call the right tool from your available tools and give the answer now."})
                    continue
                return _clean(self._final_summary(msgs, content))
            content = self.complete(msgs, temperature=0.2)
            parsed = _parse_json_call(content)
            if parsed is None or "reply" in parsed:
                return _clean(self._final_summary(msgs, parsed.get("reply", content) if parsed else content))
            result = self.executor.dispatch(parsed.get("tool"), parsed.get("args", {}))
            msgs.append({"role": "user", "content": f"Tool {parsed.get('tool')} returned: " + json.dumps(result, default=str)[:12000]})
        return "I hit my step limit — the task may need more work. Ask me to continue."

    def _final_summary(self, msgs, content):
        """If tools ran but the reply didn't report the results, force a proper closing summary."""
        used_tools = any(m.get("role") == "tool" or "returned:" in m.get("content", "") for m in msgs)
        greeting = "what are we building" in content.lower() or "co-pilot" in content.lower() or len(content) < 40
        if not (used_tools and greeting):
            return content
        msgs.append({"role": "user", "content": "The task is done and the tool results are above. Write the final reply to the user now: 2-4 short sentences — what you did, the top findings, and the exact file path if one was created. Stay in Aira's voice."})
        return self.complete(msgs, temperature=0.3)

    def _maybe_learn(self, messages, msgs):
        """Hermes-style: if the task used several tools and ended cleanly, capture
        the user wording + outcome as a breadcrumb skill so future runs reuse it.
        Deliberately lightweight — never calls the model; just stores a fact."""
        try:
            used = sum(1 for m in msgs if m.get("role") == "tool")
            if used < 3:
                return
            from .memory_store import add_fact
            user_txt = " ".join(m.get("content", "") for m in messages if m.get("role") == "user").strip()
            if not user_txt:
                return
            add_fact(
                f"[skill-signal] multi-tool task completed ({used} calls): {user_txt[:160]}",
                source="skill-signal", ttl_days=21)
        except Exception:
            pass

    def respond(self, messages):
        """Multi-agent orchestration: Swarm for tools, direct chat for talk."""
        from .swarm import Swarm
        from .memory_store import add_fact, forget_fact

        user_text = " ".join(m["content"] for m in messages if m["role"] == "user").strip()

        # --- deterministic memory/skill intents (no model drift) ---
        low = user_text.lower()
        if low.startswith(("remember ", "remember that", "remind me", "save this", "note that", "store this")):
            fact = re.sub(r"^(?:remember|remind me|save this|note that|store this)\b[:\s,]*", "", user_text, flags=re.I).strip()
            fact = re.sub(r"^that\s+", "", fact, flags=re.I).strip()
            if fact:
                add_fact(fact, source="user")
                return f"Got it — saved: {fact}"
            return "What should I remember?"
        mf = re.match(r"^(?:forget|stop remembering|remove from memory)\s+(.+)$", user_text, flags=re.I)
        if mf:
            removed = forget_fact(mf.group(1))
            return f"Forgot {removed['removed']} matching fact(s)."

        plan = self.complete(
            [
                {"role": "system", "content": "You are a planner. Reply with exactly ONE word: TOOLS if the user's request needs any tool (research, files, shell, apps, web, email, time, tts, notify, or MEMORY operations like remember/forget/save skill), or CHAT if it can be answered from knowledge alone."},
                {"role": "user", "content": user_text},
            ],
            temperature=0.0,
        ).strip().upper()
        if plan.startswith("CHAT"):
            persona = _persona()
            extra = ""
            try:
                from .memory_store import bundle, skill_trigger
                mem = bundle()
                if mem:
                    extra = f"\n\n--- AIRA'S PERSISTENT MEMORY (you can edit via tools) ---\n{mem}"
                trigger = skill_trigger(user_text)
                if trigger:
                    extra += trigger
            except Exception:
                pass
            system = SYSTEM_PROMPT + (f"\n\n--- ROHIT'S LIVE CONTEXT (read only, local) ---\n{persona}" if persona else "") + extra
            return _clean(self.complete([{"role": "system", "content": system}] + messages, temperature=0.5))
        return Swarm(self, self.executor).run(messages)


def _parse_json_tool(text):
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and "name" in data and ("arguments" in data or "args" in data):
        return {"name": data.get("name"), "arguments": data.get("arguments") or data.get("args") or {}}
    return None


def _parse_json_call(text):
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        match = re.search(r'"tool"\s*:\s*"([^"]+)"\s*,\s*"args"\s*:\s*(\{.*?\})', text[start:end + 1])
        if match:
            try:
                return {"tool": match.group(1), "args": json.loads(match.group(2))}
            except json.JSONDecodeError:
                return None
        return None
