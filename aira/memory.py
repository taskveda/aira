"""Memory strap — ingests all of Rohit's data sources into one context bundle.

Every agent in the swarm reads this so they share the same reality: who Rohit
is, how he writes, what TaskVeda is, what's been posted, what's being worked on.
Local-first, cached, capped so it never blows the model context window.
"""

import os
import time
from datetime import datetime
from pathlib import Path

from .config import DATA

HOME = Path(os.path.expanduser("~"))

# Sources that define the persona + how to work. Read whole, in order.
AI_BRAIN = HOME / "Desktop" / "AI_Brain"
CONTENT = {
    "linkedin": HOME / "LinkedIn_Content",
    "instagram": HOME / "Instagram_Content",
}
PROJECTS = {
    "taskveda": HOME / "Dev" / "taskveda-main",
    "aira": HOME / "aira",
}
DIRTY = ["node_modules", ".git", "venv", "__pycache__", ".next", "dist", "build"]

MAX_TOTAL = 15000  # hard cap on the whole strap (chars)
SECTIONS = [
    ("identity", "01_Identity.md"),
    ("writing_style", "03_Writing_Style.md"),
    ("linkedin_framework", "04_LinkedIn_Framework.md"),
    ("taskveda", "05_TaskVeda.md"),
    ("research_rules", "06_Research_Rules.md"),
    ("content_strategy", "07_Content_Strategy.md"),
    ("memory", "08_Memory.md"),
    ("system_rules", "10_System_Rules.md"),
]

_cache = None
_cache_ts = 0.0


def _read(path, limit=4000):
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(errors="replace")[:limit]
    except Exception:
        return ""


def _recent_md(directory, n=3, limit=1500):
    if not directory.exists():
        return ""
    files = sorted(
        [p for p in directory.glob("*.md") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    parts = []
    for p in files[:n]:
        parts.append(f"--- {p.name} ---\n{_read(p, limit)}")
    return "\n\n".join(parts)


def _project_scan():
    """A 1-line flavour of each active project so agents know what exists."""
    out = []
    for name, root in PROJECTS.items():
        if not root.exists():
            continue
        try:
            entries = [e.name for e in root.iterdir() if not e.name.startswith(".")]
        except Exception:
            entries = []
        out.append(f"{name}: {root} ({len(entries)} entries: {', '.join(entries[:8])})")
    return "\n".join(out)


def strap(force=False):
    """Build (and cache) the full context bundle. Returns the strap string."""
    global _cache, _cache_ts
    if not force and _cache is not None and time.time() - _cache_ts < 300:
        return _cache

    parts = ["# AIRA CONTEXT — who Rohit is, how he works, what's live"]
    parts.append(f"Strapped at {datetime.now().isoformat(timespec='seconds')}")

    for label, fname in SECTIONS:
        text = _read(AI_BRAIN / fname)
        if text:
            parts.append(f"\n## {label}\n{text}")

    parts.append("\n## recent linkedin\n" + _recent_md(CONTENT["linkedin"]))
    parts.append("\n## recent instagram\n" + _recent_md(CONTENT["instagram"]))
    parts.append("\n## active projects\n" + _project_scan())

    bundle = "\n".join(parts)
    if len(bundle) > MAX_TOTAL:
        bundle = bundle[:MAX_TOTAL] + "\n...[truncated]"
    _cache = bundle
    _cache_ts = time.time()
    return bundle


def recent_research(n=5):
    """Most recent research CSVs in ~/aira/data, as names + first rows."""
    if not DATA.exists():
        return ""
    files = sorted(DATA.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files[:n]:
        try:
            head = p.read_text(errors="replace").splitlines()[:6]
            out.append(f"{p.name}:\n" + "\n".join(head))
        except Exception:
            continue
    return "\n\n".join(out)