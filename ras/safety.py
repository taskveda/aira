import re

BLOCKED = [
    r"\brm\s+-rf\s+/\s*(;|&&|\||$)",
    r"\bdd\s+if=.*\bof=/dev/",
    r"\bdiskutil\s+erase",
    r"\bmkfs\.\w+\s+/dev/",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",
]

DANGEROUS = [
    r"\brm\b",
    r"\brmdir\b",
    r"\bsudo\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\bkill\b",
    r"\bpkill\b",
    r"\bkillall\b",
    r"\bdd\b",
    r"\bmkfs\b",
    r"\bfdisk\b",
    r"\bparted\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bpasswd\b",
    r"\buseradd\b",
    r"\buserdel\b",
    r"\bunlink\b",
    r"\btruncate\b",
    r"\bgit\s+push\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-",
    r"\bscp\b",
    r"\brsync\b",
    r"\bcurl\s+[^\n|]*\|\s*(ba|z)?sh\b",
    r">\s*/dev/(r?disk|sda)",
]


def check(command, auto=False):
    for pattern in BLOCKED:
        if re.search(pattern, command, re.IGNORECASE):
            return "blocked", "This command can damage the whole system and is never allowed."
    if auto:
        return "ok", ""
    for pattern in DANGEROUS:
        if re.search(pattern, command, re.IGNORECASE):
            return "approval", "This command is destructive or system-affecting and needs your approval."
    return "ok", ""
