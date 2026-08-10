"""Aira Content Automation — scheduled carousel, LinkedIn, briefing and blog jobs.

Runs the same Brain as chat, but driven by a deterministic job runner so the
outputs land in the right folders and the blog gets committed + pushed.

Entry points (used by main --automate and the scheduler):
  run_carousel(cfg)   -> writes next ~/Instagram_Content/NNN_Daily_Content
  run_linkedin(cfg)   -> writes next ~/LinkedIn_Content/NNN_LinkedIn_Post_*.md
  run_briefing(cfg)   -> runs ~/rohit-daily-briefing/research.py + NTFY push
  run_blog(cfg, n)    -> writes n SEO/AEO/GEO posts into blog repo + git push

All content goes through the shared memory + guard rules from
~/ai-daily-automation to avoid repeating topics and inventing facts.
"""

import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from .config import load_config

HOME = Path.home()
AUTOMATION_HOME = HOME / "ai-daily-automation"
MEMORY = AUTOMATION_HOME / "shared" / "memory.py"
GUARD = AUTOMATION_HOME / "shared" / "guard.py"

BLOG_REPO = HOME / "Dev" / "taskveda-z2c-blog"
BLOG_DIR = BLOG_REPO / "blog"
BLOG_DOMAIN = "https://blog.taskveda.in"
BASE_SITE = "https://taskveda.in"

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _run(args, timeout=120):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _mem(*args):
    _run([os.sys.executable, str(MEMORY), *args])


def _guard(*args):
    ok, out = _run([os.sys.executable, str(GUARD), *args])
    return ok, out


def next_daily_folder(base, prefix="Daily_Content"):
    """Next numbered content folder, e.g. 006_Daily_Content."""
    existing = [d for d in base.iterdir() if d.is_dir() and d.name[:3].isdigit()]
    nums = sorted(int(d.name[:3]) for d in existing) if existing else [0]
    next_num = nums[-1] + 1
    return base / f"{next_num:03d}_{prefix}"


def make_brain(cfg):
    from .brain import Brain
    from .cli import CliSession
    from .executor import ToolExecutor
    session = CliSession()
    session.config = cfg
    return Brain(cfg, ToolExecutor(session, cfg))


def _unique_topic(automation, prompt):
    """Guard against repeating a past topic; returns topic or '' if forced."""
    ok, out = _guard("check-topic", automation, prompt)
    if "REPEAT" in out.upper():
        return ""
    return prompt


# --------------------------------------------------------------------------
# Instagram carousel
# --------------------------------------------------------------------------

CAROUSEL_SYSTEM = """You are Aira planning TaskVeda Instagram carousels for a 21-year-old Indian
founder. Audience: Indian tier-2/3 college students (AI skills + internships).

You MUST NOT reuse a topic that has already been posted. You MUST ground every
claim in a real, verifiable fact — cite the source next to it. No invented
numbers, courses, or APIs.

Return PLAIN MARKDOWN in exactly this structure:

# Carousel Plan — <Month Day, Year>

## Three Carousel Topics for Today
1. <topic 1>
2. <topic 2>
3. <topic 3>

Only list 3 topics as a numbered list. Then STOP — the user will re-ask for
each full plan separately."""


def _carousel_detail_system(topic):
    return f"""You are Aira writing the FULL 10-slide carousel plan for ONE topic:
"{topic}"

Audience: Indian college students. Hook in 2 lines, real verifiable numbers,
no AI tells, no links in the body (comment-only links).

Return PLAIN MARKDOWN:
# Carousel: {topic}
## Why This Topic
## Target Audience
## Expected Engagement (save/share/comment scores out of 10)
## Complete 10 Slides
### Slide 1 — Hook
Headline: ...
Body: ...
... (through Slide 10)
## 5 Image Prompts (DALL-E/Midjourney style, one per line)"""


def run_carousel(cfg, full=True):
    base = HOME / "Instagram_Content"
    base.mkdir(parents=True, exist_ok=True)
    folder = next_daily_folder(base)
    folder.mkdir(parents=True, exist_ok=True)

    brain = make_brain(cfg)
    plan = brain.complete(
        [{"role": "system", "content": CAROUSEL_SYSTEM},
         {"role": "user", "content": f"Today is {datetime.now():%B %d, %Y}. Research is available via web_search. Give me 3 fresh carousel topics."}],
        temperature=0.8,
    )

    topic_lines = [ln for ln in plan.splitlines() if re.match(r"\d+\.\s", ln)]
    topics = [re.sub(r"^\d+\.\s*", "", ln).strip() for ln in topic_lines]

    (folder / "Carousel_Plan.md").write_text(plan)
    daily_report = f"# Daily Report — {datetime.now():%B %d, %Y}\n\n## Topics\n" + "\n".join(f"- {t}" for t in topics) + "\n"
    (folder / "Daily_Report.md").write_text(daily_report)

    image_prompts = []
    if full:
        for topic in topics:
            detail = brain.complete(
                [{"role": "system", "content": _carousel_detail_system(topic)},
                 {"role": "user", "content": f"Write the full plan for: {topic}"}],
                temperature=0.7,
            )
            (folder / f"carousel_{topics.index(topic) + 1}.md").write_text(detail if detail else f"# {topic}")
            prompts = [ln for ln in detail.splitlines() if ln.strip().startswith("- ") or re.match(r"\d", ln.strip())]
            image_prompts.extend(prompts)

    (folder / "Image_Prompts.md").write_text("\n".join(image_prompts) if image_prompts else "See carousel_N.md files for prompts.")
    _mem("add", "instagram-carousel", f"Carousel plan → {folder.name}: {topics}")
    _mem("set", "instagram-carousel", "last_topic", ", ".join(topics))
    return {"ok": True, "path": str(folder), "topics": topics}


# --------------------------------------------------------------------------
# LinkedIn post
# --------------------------------------------------------------------------

LINKEDIN_SYSTEM = """You are Aira writing a daily LinkedIn post for TaskVeda (Rohit, 21, Indian
AI-skills founder). Style: Vaibhav-style news -> what it means -> lesson ->
question. Real numbers, zero hype, no fear-bait, no links in the body
(comment-only), 1500 chars max. Ground claims in real facts with sources.

Return PLAIN MARKDOWN:
# LinkedIn Post — <Weekday, Month D, Year> (<TIME> IST)
## Type / Format / Source
## Final Post (copy-paste)
<the post>
## Posting Checklist
## Why This Post (formula check)"""


def run_linkedin(cfg):
    base = HOME / "LinkedIn_Content"
    base.mkdir(parents=True, exist_ok=True)
    brain = make_brain(cfg)

    # check today's existing post to skip duplicates
    date_tag = datetime.now().strftime("%b_%d_%Y")
    existing = list(base.glob(f"*_{date_tag}.md")) + list(base.glob("0*_LinkedIn_Post_*.md"))
    idx = len(existing) + 1
    fname = f"{idx:03d}_LinkedIn_Post_{datetime.now():%b_%d_%Y}.md"
    fpath = base / fname

    post = brain.complete(
        [{"role": "system", "content": LINKEDIN_SYSTEM},
         {"role": "user", "content": f"Today is {datetime.now():%A, %B %d, %Y}. Pull 1 fresh, today-relevant AI/edtech story via web_search and turn it into a publication-ready post."}],
        temperature=0.7,
    )
    fpath.write_text(post)
    _mem("add", "linkedin-posting", f"LinkedIn post → {fname}")
    _mem("set", "linkedin-posting", "last_topic", fname)
    return {"ok": True, "path": str(fpath)}


# --------------------------------------------------------------------------
# Daily briefing + NTFY
# --------------------------------------------------------------------------

def run_briefing(cfg):
    """Run the existing cliff research.py, then push its summary to phone via ntfy."""
    research = HOME / "rohit-daily-briefing" / "research.py"
    if not research.exists():
        return {"ok": False, "error": f"missing {research}"}
    ok, out = _run([os.sys.executable, str(research)], timeout=600)
    date = datetime.now().strftime("%Y-%m-%d")
    done = HOME / "rohit-daily-briefing" / f"briefing-{date}.md"
    ntfy_topic = "rohit-briefing-3c059a1f377dac86"
    if done.exists() and done.stat().st_size >= 500:
        title = ""
        for line in done.read_text(errors="ignore").splitlines():
            if "ROHIT DAILY AI BRIEFING" in line:
                title = line.replace("🤖 ROHIT DAILY AI BRIEFING —", "").strip()
                break
        _run(["curl", "-s", "-o", "/dev/null", "-H", f"Title: Aira Briefing {date}",
              "-H", "Priority: default", "-H", "Tags: robot",
              "-d", f"Briefing ready{': ' + title if title else ''} — open {done.name}",
              f"https://ntfy.sh/{ntfy_topic}"])
        _mem("add", "daily-briefing", f"Auto: briefing {date} generated via Aira ({done.stat().st_size} bytes)")
        return {"ok": True, "path": str(done)}
    _run(["curl", "-s", "-o", "/dev/null", "-H", "Title: Briefing FAILED", "-H", "Priority: high",
          "-H", "Tags: warning", "-d", f"research.py failed: {out[:300]}",
          f"https://ntfy.sh/{ntfy_topic}"])
    return {"ok": False, "error": out[:500]}


# --------------------------------------------------------------------------
# SEO / AEO / GEO + LLM blog posts
# --------------------------------------------------------------------------

BLOG_SYSTEM = """You are Aira writing a production SEO/AEO/GEO blog post for blog.taskveda.in
(TaskVeda — the student-confidence / AI-skills blog).

Requirements (non-negotiable):
- SEO: one primary keyword, natural H1/H2/H3, meta description, semantic LSI terms.
- AEO (answer engines): a clear, directly quotable answer in the first 60 words
  so Google/Bing AI answers and voice assistants can pull it. Include FAQ section.
- GEO (generative engine optimization): cite real, verifiable sources with URLs
  (Google/Anthropic/OpenAI/Govt/etc). High factual density, statistics with provenance.
- LLM-friendly: clean structure, first-line summary + TL;DR, definition blocks,
  tables, and a "Sources" list. No invented facts — every number needs a source.
- Target: Indian students. One topic per post. Between 1000-1800 words.

Return PLAIN MARKDOWN only, exactly:
# <H1 title>
**SEO Keyword:** <primary keyword> | **Serp Title:** <title>

## Summary (for answer engines)
<60-word directly quotable answer>

## TL;DR
- ...

## <H2 sections...>
...

## FAQ
- Q: ...  A: ...

## Sources
- <name> — <url>"""


def _slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or f"post-{int(datetime.now().timestamp())}"


def _markdown_to_html(body_md, meta):
    """Crude but safe markdown -> HTML. Keeps the JSON-LD + head separation in _post_html."""
    lines = body_md.splitlines()
    html = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("# "):
            html.append(f"<h1>{s[2:]}</h1>")
        elif s.startswith("## "):
            html.append(f"<h2>{s[3:]}</h2>")
        elif s.startswith("### "):
            html.append(f"<h3>{s[4:]}</h3>")
        elif s.startswith("- "):
            html.append(f"<li>{s[2:]}</li>")
        elif s.startswith("> "):
            html.append(f"<blockquote>{s[2:]}</blockquote>")
        elif re.match(r"\d+\.\s", s):
            html.append(f"<li>{re.sub(r'^\d+\.\s*', '', s)}</li>")
        elif re.match(r"^\*{1,2}.+\*{1,2}$", s):
            html.append(f"<p><strong>{s.strip('*')}</strong></p>")
        elif s:
            html.append(f"<p>{s}</p>")
    return "\n".join(html)


def _post_html(title, slug, date_iso, body_md, meta):
    desc = (meta.get("description") or title or "")[:160]
    kw = meta.get("keyword") or ""
    body_html = _markdown_to_html(body_md, meta)
    url = f"{BLOG_DOMAIN}/{slug}/"
    ld = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": desc,
        "url": url,
        "datePublished": date_iso,
        "inLanguage": "en",
        "author": {"@type": "Organization", "name": "TaskVeda", "url": BASE_SITE},
        "publisher": {"@type": "Organization", "name": "TaskVeda", "url": BASE_SITE},
        "isAccessibleForFree": True,
        "speakable": {"@type": "SpeakableSpecification", "cssSelector": [".speakable", "h1"]},
    }
    import json
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | TaskVeda</title>
<meta name="description" content="{desc}">
<meta name="keywords" content="{kw}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:site_name" content="TaskVeda">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld)}</script>
<style>
  body {{ max-width: 760px; margin: 0 auto; padding: 1.5rem; font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; line-height: 1.65; color: #1a1a1a; background: #fff; }}
  h1,h2,h3 {{ line-height: 1.25; color: #0b2e59; }}
  h2 {{ margin-top: 2rem; border-bottom: 1px solid #e5e7eb; padding-bottom: .4rem; }}
  li {{ margin: .3rem 0; }}
  blockquote {{ border-left: 3px solid #0b2e59; margin-left: 0; padding-left: 1rem; color: #444; }}
  a {{ color: #0b5fa8; }}
  .speakable {{ font-size: 1.06rem; }}
  footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #e5e7eb; color: #666; font-size: .9rem; }}
</style>
</head>
<body>
{body_html}
<footer>
  <p>Written by <strong>TaskVeda</strong> — AI skills + confidence for Indian students.</p>
  <p><a href="https://taskveda.in">taskveda.in</a> · <a href="{BLOG_DOMAIN}">Blog</a></p>
</footer>
</body>
</html>"""


def run_blog(cfg, n=5):
    if not BLOG_REPO.exists():
        return {"ok": False, "error": f"blog repo not found: {BLOG_REPO}"}
    (BLOG_REPO / "blog").mkdir(parents=True, exist_ok=True)
    brain = make_brain(cfg)
    today = datetime.now()
    written = []

    for i in range(n):
        post_date = today + timedelta(days=i)
        post_date_iso = post_date.strftime("%Y-%m-%d")
        mark = (post_date_iso if i == 0 else today.strftime("%Y-%m-%d"))
        prompt = (
            f"Write blog post #{i + 1} of {n} for {post_date_iso}. "
            f"Pick a fresh, in-demand topic for Indian students around confidence, "
            f"AI skills, internships, or careers. Use web_search to ground every claim "
            f"with real sources before writing."
        )
        body = brain.complete(
            [{"role": "system", "content": BLOG_SYSTEM},
             {"role": "user", "content": prompt}],
            temperature=0.7,
        )
        title = body.splitlines()[0].lstrip("# ").strip() if body.splitlines() else f"Post {mark}"
        slug = _slugify(title)
        kw_m = re.search(r"\*\*SEO Keyword:\*\*\s*([^*]+?)\s*\*", body) or re.search(r"SEO Keyword[:：]\s*([^\n]+)", body)
        desc_m = re.search(r"(?m)^## Summary[^\n]*\n(.{10,200})", body)
        meta = {
            "keyword": kw_m.group(1).strip() if kw_m else "",
            "description": re.sub(r"[^A-Za-z0-9 .,'-]", "", (desc_m.group(1).strip() if desc_m else ""))[:160],
        }
        out_dir = BLOG_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(_post_html(title, slug, post_date_iso, body, meta))
        written.append({"slug": slug, "title": title, "date": post_date_iso, "path": str(out_dir / "index.html")})

    ok, out = _run(["git", "-C", str(BLOG_REPO), "add", "-A"])
    ok2, out2 = _run(["git", "-C", str(BLOG_REPO), "commit", "-m", f"Aira: {n} SEO/AEO/GEO blog posts ({today:%Y-%m-%d})"])
    push_ok, push_out = _run(["git", "-C", str(BLOG_REPO), "push", "origin", "main"], timeout=300)
    _mem("add", "blog", f"Auto: {n} blog posts ({', '.join(w['slug'] for w in written)}) committed+{'pushed' if push_ok else 'local'}")
    return {
        "ok": True,
        "posts": written,
        "commit": ok2 and not "nothing to commit" in out2.lower(),
        "push": push_ok,
        "push_output": push_out[:300],
    }


JOBS = {
    "carousel": run_carousel,
    "linkedin": run_linkedin,
    "briefing": run_briefing,
    "blog": run_blog,
}


def run_automation(cfg, name, **kwargs):
    fn = JOBS.get(name)
    if fn is None:
        return {"ok": False, "error": f"unknown automation '{name}'. Choose from: {', '.join(JOBS)}"}
    try:
        return fn(cfg, **kwargs)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Aira content automation runner")
    p.add_argument("name", choices=list(JOBS))
    p.add_argument("--count", type=int, default=5, help="number of blog posts (blog only)")
    args = p.parse_args()
    cfg = load_config()
    res = run_automation(cfg, args.name, n=args.count) if args.name == "blog" else run_automation(cfg, args.name)
    import json
    print(json.dumps(res, indent=2, default=str))
