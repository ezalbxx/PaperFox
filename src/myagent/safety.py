"""Capability guards, not an operating-system sandbox."""
from __future__ import annotations

import re


EXECUTION_TOOLS = frozenset({"run_shell", "run_python", "start_job"})
_DANGER = re.compile(
    r"(?i)(?:\b(?:rm|rmdir|del|erase|remove-item|diskpart|mkfs|shutdown|reboot|pkill|killall)\b|\bformat\b(?!-(?:table|list|wide|custom|hex)\b)"
    r"|\bgit\s+(?:reset\s+--hard|clean\b)|\b(?:invoke-expression|iex)\b"
    r"|\b(?:curl|wget)\b[^\n]*\|\s*(?:sh|bash|powershell|pwsh)\b)"
)


def authorize(name: str, args: dict, policy: str) -> None:
    if policy not in ("guarded", "trusted"):
        raise PermissionError("unknown execution policy")
    if name in EXECUTION_TOOLS and policy != "trusted":
        raise PermissionError(
            "process execution disabled in guarded mode; the user must select --execution-policy trusted"
        )
    command = args.get("command", "") if name == "run_shell" else ""
    if name == "start_job":
        command = " ".join(str(x) for x in args.get("argv", []))
    if _DANGER.search(command):
        raise PermissionError("dangerous command rejected; use a reviewed, scoped operation")
