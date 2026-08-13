"""Swarm — multi-agent orchestration loop for Aira.

Instead of one agent doing everything in a single tool loop, a swarm of
specialist agents each own a domain. An orchestrator routes the task, fans
the work out to the specialists that matter, collects their draft answers,
and iterates until the job is done. All agents share the strapped context
from memory.py so they operate on the same reality.

Round model (each round is one orchestrator decision):
  orchestrator(decide) -> dispatch 1..N specialists -> collect drafts
  -> orchestrator(assess): DONE, or loop again with revision notes.
"""

import json

from . import memory
from .brain import SYSTEM_PROMPT, TOOLS, _clean

MAX_SPECIALISTS_PER_ROUND = 3
MAX_ROUNDS = 4

# Every specialist can also maintain Aira's memory/skills mid-task.
MEMORY_TOOLS = ["memory_add", "memory_forget", "learn_skill", "skill_use"]

# Each specialist: a persona contract + the tools it is allowed to use.
SPECIALISTS = {
    "content": {
        "name": "Content Agent",
        "tools": ["run_shell", "list_dir", "read_file", "write_file", "web_search", "fetch_url", "get_time", "open_app"] + MEMORY_TOOLS,
        "system": """You are AIRA's CONTENT AGENT. You own LinkedIn + Instagram output for Rohit (TaskVeda founder).
Use his writing style, the FIMA framework, and the source material in context. Deliver a finished,
publication-ready post (hook + body + 1 quotable line + ending question + max 5 hashtags on the final line).
No AI tells. Real numbers. Forbidden words: game changer, revolutionary, 'AI is changing everything', 'in today's world'.
Never ask 'What do you think?'. Open-ended question requiring experience to answer. Post only, no preamble.""",
    },
    "research": {
        "name": "Research Agent",
        "tools": ["web_search", "fetch_url", "rss_read", "research_to_csv", "read_file", "write_file", "get_time"] + MEMORY_TOOLS,
        "system": """You are AIRA's RESEARCH AGENT. Verify every claim against 2+ independent sources. Never fabricate facts,
statistics, or quotes. Show confidence (HIGH/MEDIUM/LOW) and cite sources. Separate fact from interpretation from
speculation. For founder analysis, state the implication and the hidden opportunity. Use research_to_csv to save
structured findings to ~/aira/data when there are multiple results. Prefer his research rules from context.""",
    },
    "email": {
        "name": "Email Agent",
        "tools": ["run_shell", "read_file", "write_file", "get_time"] + MEMORY_TOOLS,
        "system": """You are AIRA's EMAIL AGENT. Triage the inbox: kill spam, draft replies in Rohit's direct, decisive voice,
escalate only what truly needs his eyes (money, reputation, his words). Digest, never dump. For each important item:
one-line summary + a ready-to-send reply. Never invent emails that don't exist — if you can't read mail, say exactly
that and give the triage rules instead.""",
    },
    "deals": {
        "name": "Brand Deals Agent",
        "tools": ["web_search", "read_file", "write_file", "run_shell", "get_time"] + MEMORY_TOOLS,
        "system": """You are AIRA's BRAND DEALS AGENT. Your job is inbound money. Spot opportunities, qualify them fast,
and produce a short opportunity note + a draft outreach/negotiation reply in Rohit's voice. Every deal = a note +
a draft. Be specific about terms (rate, deliverables, timeline). Never accept a deal on his behalf — present options.""",
    },
    "exec": {
        "name": "Executor Agent",
        "tools": ["run_shell", "list_dir", "read_file", "write_file", "search_files", "open_app", "osascript", "get_time"] + MEMORY_TOOLS,
        "system": """You are AIRA's EXECUTOR AGENT. You get things done on the Mac: shell, files, apps, research-to-disk.
Do the work, verify it (re-read the file / re-run the command), and report exactly what you did and where it's saved.
Safe actions run immediately; destructive/system-changing commands (rm, sudo, kill, overwrites) require approval.
Never claim work you didn't do; report exact errors.""",
    },
}


def _routing_prompt(task):
    return (
        "You are the ORCHESTRATOR for Aira, a multi-agent personal assistant. Route the task below to the "
        "specialist agents that can actually complete it. Reply with ONLY a JSON object, nothing else.\n"
        f'{{"agents": ["content", "research", "email", "deals", "exec"], "plan": "<one short line explaining the order>"}}\n'
        "Rules:\n"
        "- Include ONLY specialist ids that are needed. An empty list [] means this is a chat-only task.\n"
        f"- Pick at most {MAX_SPECIALISTS_PER_ROUND} agents per round.\n"
        "- content: writing/posting LinkedIn or Instagram.\n"
        "- research: web research, verification, gathering info, saving to CSV.\n"
        "- email: anything about the inbox or email.\n"
        "- deals: brand deals, sponsorships, partnerships, outreach.\n"
        "- exec: files, shell, apps, running anything on the Mac.\n"
        f"\nTASK:\n{task}"
    )


def _assess_prompt(task, drafts):
    return (
        "You are the ORCHESTRATOR for Aira. The specialist agents produced the drafts below for his task. "
        "Decide if the job is DONE. Reply with ONLY a JSON object:\n"
        '{"done": true|false, "final": "<the final answer to show Rohit, in Aira voice>"}\n'
        'or if not done: {"done": false, "revision": "<concise instruction to the specialists on what is still missing>"}\n'
        "Rules:\n"
        "- If the final answer is ready (facts complete, output saved, decision made), done=true with final.\n"
        "- If a draft is obviously wrong, empty, or missing the ask, done=false with a specific revision.\n"
        "- Keep the final answer in Aira's voice: direct, no fluff, bring decisions not homework.\n"
        f"\nTASK:\n{task}\n\nDRAFTS:\n{drafts}"
    )


class Swarm:
    def __init__(self, brain, executor):
        self.brain = brain
        self.executor = executor
        self.context = memory.strap()

    def _specialist_run(self, agent_id, task):
        """Run one specialist agent (with its own tools) over the task. Returns its draft answer."""
        spec = SPECIALISTS[agent_id]
        tools = [t for t in TOOLS if t["function"]["name"] in spec["tools"]]
        system = self.context + "\n\n" + spec["system"] + "\n\n" + SYSTEM_PROMPT
        try:
            from .memory_store import skill_trigger
            system += skill_trigger(task)
        except Exception:
            pass
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]
        return self._run_with_tools(msgs, tools)

    def _run_with_tools(self, msgs, tools):
        messages = list(msgs)
        if self.brain.ollama:
            content, calls = self.brain.ollama.chat(messages, tools=tools)
            if calls:
                for call in calls:
                    fn = call.get("function", {})
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    result = self.executor.dispatch(fn.get("name"), args)
                    messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(result, default=str)[:12000]})
                return self._run_with_tools(messages, tools)
            return _clean(content)
        for _ in range(10):
            resp = self.brain.client.chat.completions.create(
                model=self.brain.model, messages=messages, tools=tools, temperature=0.3, max_tokens=2048
            )
            msg = resp.choices[0].message
            if msg.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments or ""}}
                        for c in msg.tool_calls
                    ],
                })
                for c in msg.tool_calls:
                    try:
                        args = json.loads(c.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {"command": c.function.arguments or ""}
                    result = self.executor.dispatch(c.function.name, args)
                    messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, default=str)[:12000]})
                continue
            return _clean(msg.content or "")
        return "Specialist hit its step limit."

    def run(self, messages):
        task = " ".join(m["content"] for m in messages if m["role"] == "user")
        if not task.strip():
            return "What's the task?"

        # 1. Route.
        routing = self.brain.complete([{"role": "user", "content": _routing_prompt(task)}], temperature=0.0)
        try:
            plan = json.loads(routing[routing.find("{"): routing.rfind("}") + 1])
        except Exception:
            plan = {"agents": [], "plan": routing}
        agents = [a for a in plan.get("agents", []) if a in SPECIALISTS][:MAX_SPECIALISTS_PER_ROUND]

        # Chat-only task — no specialists needed.
        if not agents:
            system = SYSTEM_PROMPT
            try:
                from .memory_store import skill_trigger
                system += skill_trigger(task)
            except Exception:
                pass
            return _clean(self.brain.complete([{"role": "system", "content": system}] + messages, temperature=0.5))

        # 2. Fan out.
        drafts = []
        for aid in agents:
            try:
                draft = self._specialist_run(aid, task)
            except Exception as exc:
                draft = f"[{aid} failed: {exc}]"
            drafts.append(f"### {aid} ({SPECIALISTS[aid]['name']})\n{draft}")

        # 3. Assess + iterate.
        draft_block = "\n\n".join(drafts)
        for _ in range(MAX_ROUNDS):
            assess = self.brain.complete([{"role": "user", "content": _assess_prompt(task, draft_block)}], temperature=0.0)
            try:
                verdict = json.loads(assess[assess.find("{"): assess.rfind("}") + 1])
            except Exception:
                break
            if verdict.get("done"):
                return _clean(verdict.get("final") or draft_block)
            revision = verdict.get("revision", "")
            if not revision:
                break
            rerun = []
            for aid in agents:
                try:
                    rerun.append(f"### {aid}\n{self._specialist_run(aid, task + '\n\nREVISION: ' + revision)}")
                except Exception as exc:
                    rerun.append(f"### {aid}\n[{aid} failed: {exc}]")
            draft_block = "\n\n".join(rerun)

        return _clean(draft_block)