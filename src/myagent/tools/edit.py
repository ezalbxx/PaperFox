from __future__ import annotations

import hashlib
import os
import tempfile

from .base import ToolContext, ToolResult, resolve_workspace_path


class EditFileTool:
    name = "edit_file"
    description = "Replace exactly one literal match in a UTF-8 file. Preserve BOM/newlines. Zero or multiple matches fail without changes."
    parameters = {"type": "object", "properties": {
        "path": {"type": "string"}, "old_text": {"type": "string"},
        "new_text": {"type": "string"},
        "expected_sha256": {"type": "string", "description": "optional stale-read protection"},
    }, "required": ["path", "old_text", "new_text"]}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        path = resolve_workspace_path(ctx.workspace, args["path"])
        old, new = args["old_text"], args["new_text"]
        if not isinstance(old, str) or not old or not isinstance(new, str):
            return ToolResult(-1, error="old_text must be nonempty and new_text must be a string")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if args.get("expected_sha256") and args["expected_sha256"] != digest:
            return ToolResult(-1, error="stale read: SHA-256 mismatch")
        text = raw.decode("utf-8")
        # Adapt LF tool arguments to an existing consistently CRLF file.
        if "\r\n" in text and "\n" not in text.replace("\r\n", ""):
            old = old.replace("\r\n", "\n").replace("\n", "\r\n")
            new = new.replace("\r\n", "\n").replace("\n", "\r\n")
        count = text.count(old)
        if count != 1:
            return ToolResult(-1, error=f"expected one match; found {count}; file unchanged")
        updated = text.replace(old, new, 1).encode("utf-8")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".myagent-edit-", delete=False) as fh:
                temporary = fh.name
                fh.write(updated)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(temporary, path.stat().st_mode)
            if path.read_bytes() != raw:
                return ToolResult(-1, error="file changed during edit; retry after reading")
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary:
                os.unlink(temporary)
        return ToolResult(0, f"replaced one match in {args['path']}; sha256={hashlib.sha256(updated).hexdigest()}")
