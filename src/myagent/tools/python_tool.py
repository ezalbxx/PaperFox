from __future__ import annotations

import os
import subprocess
from uuid import uuid4

from .base import (ToolContext, ToolResult, resolve_workspace_path,
                   collect_process, decode_utf8, truncate_output)


class PythonTool:
    name = "run_python"
    description = (
        "Run Python code or a Python file with the same interpreter as the agent. "
        "Use this for file/text processing, tests, and small scripts."
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python source to run. Use either code or path."},
            "path": {"type": "string", "description": "Path to a .py file inside the workspace."},
            "timeout_s": {"type": "integer", "description": "Timeout in seconds."},
        },
    }

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        """Run Python with the same interpreter as the agent.

        Contract:
        - exactly one of code/path; both or neither -> error observation
        - code: write to <workspace>/.myagent/tmp/run_<id>.py
        - path: resolve inside workspace; reject ../ and absolute escapes
        - command: [ctx.python_exe, "-X", "utf8", <file>], cwd=workspace
        - env: PYTHONUTF8=1, PYTHONIOENCODING=utf-8
        - timeout: kill the whole process tree, return code -1, error contains
          "timeout"
        - return stdout+stderr, decoded UTF-8 with errors="replace"
        """
        from ..safety import authorize
        authorize(self.name, args, ctx.execution_policy)
        if ("code" in args) == ("path" in args):
            return ToolResult(-1, error="provide exactly one of code/path")
        generated = None
        try:
            timeout = int(args.get("timeout_s", ctx.timeout_s))
            if timeout <= 0:
                return ToolResult(-1, error="timeout_s must be positive")
            if "code" in args:
                if not isinstance(args["code"], str):
                    return ToolResult(-1, error="code must be a string")
                temp_dir = resolve_workspace_path(ctx.workspace, ".myagent/tmp", internal=True)
                temp_dir.mkdir(parents=True, exist_ok=True)
                generated = temp_dir / f"run_{uuid4().hex}.py"
                generated.write_text(args["code"], encoding="utf-8")
                path = generated
            else:
                if not isinstance(args["path"], str) or not args["path"]:
                    return ToolResult(-1, error="path must be a non-empty string")
                path = resolve_workspace_path(ctx.workspace, args["path"])
                if not path.is_file():
                    return ToolResult(-1, error=f"not a file: {args['path']}")
            env = os.environ | {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.Popen(
                [ctx.python_exe, "-X", "utf8", str(path)], cwd=str(ctx.workspace),
                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=os.name == "posix",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
            out, error = collect_process(proc, ctx, timeout)
            output, truncated = truncate_output(decode_utf8(out), ctx.max_output_chars)
            return ToolResult(-1 if error else proc.returncode, output, error=error, truncated=truncated)
        except Exception as exc:
            return ToolResult(-1, error=f"{type(exc).__name__}: {exc}")
        finally:
            if generated is not None:
                generated.unlink(missing_ok=True)
