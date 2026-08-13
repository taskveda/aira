"""Self-editing memory + self-improving skills (Letta-style memory blocks +
Hermes-style skill learning) for Aira.

Aira keeps a persistent store next to its data dir:
    ~/aira/data/memory.json   — running facts + experience, editable live
    ~/aira/data/skills/       — reusable "recipes" learned from real tasks

Every Brain run injects the current memory bundle into the system prompt, and
Aira can rewrite/recall/forget it mid-conversation through tools, so it stops
being a stateless chat and starts behaving like a chief of staff that genuinely
remembers.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

from .config import DATA

MEMORY_FILE = DATA / "memory.json"
SKILLS_DIR = DATA / "skills"

MAX_FACTS = 60          # cap on remembered facts
MAX_FACT_LEN = 280      # per-fact length
MAX_MEMORY_STR = 6000   # hard cap on the memory block injected into context
MAX_SKILLS = 30
MAX_SKILL_LEN = 1200


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _load():
    if not MEMORY_FILE.exists():
        return {"facts": []}
    try:
        data = json.loads(MEMORY_FILE.read_text(errors="replace"))
        if isinstance(data, dict) and isinstance(data.get("facts"), list):
            return data
        return {"facts": []}
    except Exception:
        return {"facts": []}


def _save(data):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = MEMORY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(MEMORY_FILE)


# ---------------------------------------------------------------- facts

def add_fact(text, source="assistant", ttl_days=None):
    """Remember a durable fact. Returns the new fact."""
    text = " ".join(str(text).split())
    if not text or len(text) > MAX_FACT_LEN:
        return {"ok": False, "error": f"fact too long/empty ({len(text)} chars)"}
    data = _load()
    facts = data["facts"]
    # de-dupe by normalized text
    norm = text.lower()
    facts = [f for f in facts if norm not in f["text"].lower()]
    expiry = None
    if ttl_days:
        expiry = int(time.time()) + int(ttl_days) * 86400
    facts.append({
        "text": text,
        "source": source,
        "ts": _now(),
        "expiry": expiry,
    })
    # keep newest MAX_FACTS
    facts.sort(key=lambda f: f.get("ts", ""), reverse=True)
    data["facts"] = facts[:MAX_FACTS]
    _save(data)
    return {"ok": True, "saved": text}


def forget_fact(needle):
    """Remove facts containing needle. Returns how many were removed."""
    data = _load()
    before = len(data["facts"])
    needle = needle.lower()
    data["facts"] = [f for f in data["facts"] if needle not in f["text"].lower()]
    _save(data)
    return {"ok": True, "removed": before - len(data["facts"])}


def query_facts(needle="", limit=8):
    """Search stored facts (filters expired)."""
    data = _load()
    nowish = int(time.time())
    facts = [f for f in data["facts"] if not f.get("expiry") or f["expiry"] > nowish]
    needle = needle.lower()
    if needle:
        facts = [f for f in facts if needle in f["text"].lower()]
    return facts[:limit]


# ---------------------------------------------------------------- skills

def learn_skill(name, description, recipe, tags=None):
    """Save a reusable skill/recipe learned from a completed task (Hermes-style)."""
    name = " ".join(str(name).split())[:80]
    if not name or len(recipe) < 10:
        return {"ok": False, "error": "skill needs a name and a real recipe"}
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    existing = [p.stem.lower() for p in SKILLS_DIR.glob("*.json")]
    if name.lower() in existing:
        return {"ok": False, "error": f"skill '{name}' already exists — delete it first or pick another name"}
    existing.sort()
    if len(existing) >= MAX_SKILLS:
        return {"ok": False, "error": "skill store full — delete some skills first"}
    skill = {
        "name": name,
        "description": str(description)[:300],
        "recipe": str(recipe)[:MAX_SKILL_LEN],
        "tags": list(tags or []),
        "created": _now(),
        "times_used": 0,
        "last_used": None,
    }
    safe = "".join(c for c in name if c.isalnum() or c in " _-").strip().replace(" ", "_")
    (SKILLS_DIR / f"{safe or 'skill'}.json").write_text(
        json.dumps(skill, indent=2, ensure_ascii=False)
    )
    return {"ok": True, "name": name}


def _skill_path(name):
    """Resolve a skill's file by name (spaces <-> underscores, case-insensitive)."""
    name = " ".join(str(name).split())
    if not name:
        return None
    wanted = name.replace(" ", "_").lower()
    if not SKILLS_DIR.exists():
        return None
    for p in SKILLS_DIR.glob("*.json"):
        if p.stem.lower() == wanted:
            return p
    return None


def get_skill(name):
    """Load one full skill record (name, description, recipe, tags) or None."""
    p = _skill_path(name)
    if not p:
        return None
    try:
        return json.loads(p.read_text(errors="replace"))
    except Exception:
        return None


def use_skill(name):
    """Mark a skill as used (so Aira learns which recipes actually help) and
    return its full record, or None if it doesn't exist."""
    skill = get_skill(name)
    if not skill:
        return None
    try:
        skill["times_used"] = skill.get("times_used", 0) + 1
        skill["last_used"] = _now()
        _skill_path(name).write_text(json.dumps(skill, indent=2, ensure_ascii=False))
    except Exception:
        pass
    return skill


def find_skill(task, min_score=1):
    """Best matching saved skill for a task, scored on keyword overlap with the
    skill's name/tags/description. Returns the full record or None."""
    task = " ".join(str(task).split()).lower()
    if not task or not SKILLS_DIR.exists():
        return None
    words = set(re.findall(r"[a-z0-9]+", task))
    if not words:
        return None
    stop = {"a", "an", "the", "to", "of", "for", "and", "or", "with", "in", "on", "at", "how", "do", "i", "you", "me", "my", "is", "it", "this", "that"}
    keywords = {w for w in words if len(w) > 2 and w not in stop}
    if not keywords:
        return None
    best, best_score = None, 0
    for p in sorted(SKILLS_DIR.glob("*.json")):
        try:
            skill = json.loads(p.read_text(errors="replace"))
        except Exception:
            continue
        hay = " ".join([
            skill.get("name", ""),
            skill.get("description", ""),
            " ".join(skill.get("tags", [])),
        ]).lower()
        hay_words = set(re.findall(r"[a-z0-9]+", hay))
        score = sum(1 for w in keywords if w in hay_words)
        if score > best_score:
            best, best_score = skill, score
    if best_score >= min_score:
        return best
    return None


def skill_trigger(task):
    """Auto-trigger: if a saved skill matches the task, mark it used and return
    a context block teaching Aira the recipe — so it reuses, not reinvents."""
    skill = find_skill(task)
    if not skill:
        return ""
    use_skill(skill.get("name", ""))
    return (
        "\n\n--- ACTIVE SKILL (this task matches one you learned) ---\n"
        f"Name: {skill.get('name')}\n"
        f"What it's for: {skill.get('description')}\n"
        f"Recipe — follow it, don't reinvent:\n{skill.get('recipe')}"
    )


def list_skills(needle=""):
    if not SKILLS_DIR.exists():
        return []
    needle = needle.lower()
    out = []
    for p in sorted(SKILLS_DIR.glob("*.json")):
        try:
            skill = json.loads(p.read_text(errors="replace"))
        except Exception:
            continue
        if needle and needle not in skill.get("name", "").lower() and needle not in skill.get("description", "").lower():
            continue
        out.append({
            "name": skill.get("name"),
            "description": skill.get("description"),
            "tags": skill.get("tags", []),
            "times_used": skill.get("times_used", 0),
        })
    return out


def delete_skill(name):
    p = _skill_path(name)
    if not p:
        return {"ok": False, "error": f"no skill named '{name}'"}
    p.unlink()
    return {"ok": True, "deleted": name}


# ---------------------------------------------------------------- bundle

def bundle():
    """Compact memory + skills block to inject into the system prompt."""
    parts = []

    facts = query_facts()
    if facts:
        parts.append("## PERSISTENT MEMORY (remember these)")
        for i, f in enumerate(facts[:20], 1):
            parts.append(f"{i}. {f['text']}")

    skills = list_skills()
    if skills:
        parts.append("## LEARNED SKILLS (use the right one, don't reinvent)")
        for s in skills[:15]:
            parts.append(f"- {s['name']}: {s['description']}")

    block = "\n".join(parts)
    if len(block) > MAX_MEMORY_STR:
        block = block[:MAX_MEMORY_STR] + "\n..."
    return block


def auto_remember(task, reply, ok=True):
    """After a task, quietly log an experience so Aira gets better over time.
    Short, keyword-sparse, never invented facts — just a breadcrumb."""
    task = " ".join(str(task).split())
    reply = " ".join(str(reply).split())
    if not task:
        return
    note = f"Task done: {task[:140]} -> {reply[:180]}"
    add_fact(note, source="experience", ttl_days=14)