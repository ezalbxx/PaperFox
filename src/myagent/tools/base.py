from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass
class ToolResult:
    returncode: int = 0
    output: str = ""
    error: str = ""
    truncated: bool = False
    images: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        result = {
            "returncode": self.returncode,
            "output": self.output,
            "error": self.error,
            "truncated": self.truncated,
        }
        if self.images:
            result['images'] = [{k: v for k, v in item.items() if k != 'url'} for item in self.images]
        return result


@dataclass
class ToolContext:
    workspace: Path
    timeout_s: int = 120
    max_output_chars: int = 8000
    python_exe: str = field(default_factory=lambda: sys.executable)
    shell_backend: str = "auto"
    submitted: bool = False
    submission: str = ""
    execution_policy: str = "trusted"
    skill_dirs: tuple[Path, ...] = ()
    cancel_requested: Callable[[], bool] | None = None
    deadline: float | None = None
    on_wait: Callable[[float], None] | None = None
    image_inputs_enabled: bool = False


class Tool(Protocol):
    name: str
    description: str
    parameters: dict

    def run(self, args: dict, ctx: ToolContext) -> ToolResult: ...


def decode_utf8(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace")


def truncate_output(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    head = max_chars // 2
    tail = max_chars - head
    omitted = len(text) - max_chars
    return (
        text[:head]
        + f"\n... [{omitted} chars omitted] ...\n"
        + text[-tail:],
        True,
    )


def resolve_workspace_path(workspace: Path, raw: str | None, *, internal: bool = False) -> Path:
    workspace = workspace.resolve()
    if not raw:
        return workspace
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    if resolved != workspace and workspace not in resolved.parents:
        raise ValueError(f"path escapes workspace: {raw}")
    relative = resolved.relative_to(workspace)
    for part in relative.parts:
        low = part.lower()
        if low in (".ssh", ".aws", ".git") or (low == ".myagent" and not internal):
            raise ValueError(f"protected internal path: {part}")
        if (low == ".env" or low.startswith(".env.")) and low != ".env.example":
            raise ValueError("protected credentials file")
        if low in ("id_rsa", "id_ed25519", ".credentials.yaml", "credentials.json"):
            raise ValueError("protected credentials file")
    return resolved


def kill_process_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


def collect_process(proc, ctx: ToolContext, timeout: float) -> tuple[bytes, str]:
    """Collect one owned process, responding to interactive pause and turn limits."""
    started = time.monotonic()
    deadline = min(started + timeout, ctx.deadline) if ctx.deadline is not None else started + timeout
    next_notice = started
    while True:
        point = time.monotonic()
        error = ('interrupted by user; foreground process stopped' if ctx.cancel_requested and ctx.cancel_requested()
                 else 'turn deadline reached' if ctx.deadline is not None and point >= ctx.deadline
                 else f'timeout after {timeout:g}s' if point >= deadline else '')
        if error:
            kill_process_tree(proc.pid)
            out, _ = proc.communicate()
            return out or b'', error
        if ctx.on_wait and point >= next_notice:
            ctx.on_wait(point-started)
            next_notice = point + 1
        try:
            out, _ = proc.communicate(timeout=min(.1, deadline-point))
            return out or b'', ''
        except subprocess.TimeoutExpired:
            continue
