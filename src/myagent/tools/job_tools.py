from __future__ import annotations

import json

from ..jobs import JobManager
from .base import ToolContext, ToolResult


class StartJobTool:
    name = "start_job"
    description = "Start a persistent background process using argv (no shell). Trusted mode required. At most 2 jobs; survives foreground exit. GPU jobs require a resource check first."
    parameters = {"type": "object", "properties": {
        "argv": {"type": "array", "items": {"type": "string"}},
        "max_seconds": {"type": "number", "description": "separate job deadline, default 3600"},
    }, "required": ["argv"]}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from ..safety import authorize
        authorize(self.name, args, ctx.execution_policy)
        data = JobManager(ctx.workspace).start(args["argv"], max_seconds=args.get("max_seconds", 3600), python_exe=ctx.python_exe)
        return ToolResult(0, json.dumps(data, ensure_ascii=False))


class JobStatusTool:
    name = "job_status"
    description = "Query persistent job state. Optionally wait up to 30 seconds; waiting does not terminate the job."
    parameters = {"type": "object", "properties": {"job_id": {"type": "string"}, "wait_seconds": {"type": "number"}}, "required": ["job_id"]}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(0, json.dumps(JobManager(ctx.workspace).status(args["job_id"], args.get("wait_seconds", 0)), ensure_ascii=False))


class JobLogsTool:
    name = "job_logs"
    description = "Read bounded tails of a job's separate stdout/stderr/worker logs."
    parameters = {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(0, json.dumps(JobManager(ctx.workspace).logs(args["job_id"], ctx.max_output_chars // 3), ensure_ascii=False))


class CancelJobTool:
    name = "cancel_job"
    description = "Request cancellation of an owned workspace job. Poll status for actual termination; never accepts a PID."
    parameters = {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(0, json.dumps(JobManager(ctx.workspace).cancel(args["job_id"])))
