from __future__ import annotations

import json
import time
from pathlib import Path
from enum import Enum

from .config import Config
from .context import maybe_compact
from .session import resume_state
from .environment import detect_environment
from .events import NullLogger
from .prompts import build_instance_prompt, build_system_prompt
from .tools.base import ToolContext, ToolResult
from .tools.registry import ToolRegistry


class StopReason(str, Enum):
    SUBMIT = "Submitted"
    FINAL_ANSWER = "FinalAnswer"
    MAX_STEPS = "MaxSteps"
    MAX_COST = "MaxCost"
    MAX_SECONDS = "MaxSeconds"


class Agent:
    def __init__(
        self,
        model,
        tools: ToolRegistry,
        config: Config,
        logger=None,
    ):
        self.model = model
        self.tools = tools
        self.config = config
        self.logger = logger or NullLogger()
        self.messages: list[dict] = []
        self.ctx = ToolContext(
            workspace=config.workspace,
            timeout_s=config.timeout_s,
            max_output_chars=config.max_output_chars,
            python_exe=config.python_exe,
            shell_backend=config.shell_backend,
            execution_policy=config.execution_policy,
            skill_dirs=config.skill_dirs,
        )
        self.steps = 0
        self.cost = 0.0
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.stop_reason: StopReason | None = None
        self.final_text = ""
        self._started = time.time()

    def run(self, task: str = "", *, resume_path: Path | None = None) -> dict:
        """Bootstrap the messages, loop until should_stop(), return a result dict.

        Contract:
        1. messages start with system + user (use build_system_prompt /
           build_instance_prompt and detect_environment).
        2. Log run_start / every message / run_end through self.logger.
        3. Loop: call should_stop(); if None, call step().
        4. Return {"exit_status", "submission", "steps", "cost", "usage"}.

        Hint: `exit_status` is `self.stop_reason.value`; the loop must set
        `self.stop_reason` to the reason returned by should_stop().
        """
        self.messages = []
        self.steps = 0
        self.cost = 0.0
        self.usage = dict.fromkeys(("prompt_tokens", "completion_tokens", "total_tokens"), 0)
        self.stop_reason = None
        self.final_text = ""
        self.ctx.submitted = False
        self.ctx.submission = ""
        self._started = time.time()
        inherited = {}
        restored = []
        if resume_path is not None:
            state = resume_state(Path(resume_path))
            if state.get("workspace") and Path(state["workspace"]).resolve() != self.config.workspace:
                raise ValueError("resume workspace mismatch")
            if not task and state.get("exit_status") in ("Submitted", "FinalAnswer"):
                raise ValueError("session already completed; provide a follow-up task")
            restored = state.pop("messages")
            if not restored:
                raise ValueError("cannot resume an empty session")
            inherited = {k: state[k] for k in ("steps", "cost", "usage", "elapsed_seconds")}
            self.steps, self.cost = state["steps"], state["cost"]
            self.usage.update(state["usage"])
            self._started -= state["elapsed_seconds"]
        elif not task.strip():
            raise ValueError("task must not be empty")
        env = detect_environment()
        env["workspace"] = str(self.config.workspace)
        env["python"] = self.config.python_exe
        names = [s["function"]["name"] for s in self.tools.schemas()]
        self.logger.run_start(task=task, model=self.config.model,
                              workspace=str(self.config.workspace), cost_currency="USD",
                              execution_policy=self.config.execution_policy,
                              provider=self.config.provider, base_url=self.config.base_url,
                              context_max_tokens=self.config.context_max_tokens,
                              context_keep_last=self.config.context_keep_last,
                              max_steps=self.config.max_steps, max_cost=self.config.max_cost,
                              max_seconds=self.config.max_seconds,
                              resumed_from=str(resume_path) if resume_path else None,
                              inherited=inherited)
        try:
            initial = restored or [
                {"role": "system", "content": build_system_prompt(env, names) +
                 f"\nExecution policy: {self.config.execution_policy}."},
                {"role": "user", "content": build_instance_prompt(task, env)},
            ]
            if restored and task:
                initial = initial + [{"role": "user", "content": task}]
            for message in initial:
                self.messages.append(message)
                self.logger.message(message)
            while True:
                reason = self.should_stop()
                if reason is not None:
                    self.stop_reason = reason
                    break
                self.step()
        except BaseException as exc:
            self.logger.log("run_error", error_type=type(exc).__name__, error=str(exc))
            self.logger.run_end(exit_status="Interrupted" if isinstance(exc, KeyboardInterrupt) else "Error", steps=self.steps, cost=self.cost,
                                usage=self.usage, elapsed_seconds=time.time() - self._started)
            raise
        result = {"exit_status": self.stop_reason.value, "submission": self.final_text,
                  "steps": self.steps, "cost": self.cost, "usage": dict(self.usage)}
        self.logger.run_end(**result, elapsed_seconds=time.time() - self._started,
                            cost_currency="USD")
        return result

    def step(self) -> None:
        """One model call, then execute every tool call in the response.

        Contract:
        1. Increment self.steps.
        2. response = self.model.chat(self.messages, self.tools.schemas()).
        3. Add response["cost"] and response["usage"] to self.cost / self.usage.
        4. Append response["message"] (assistant) and log it.
        5. If there are no tool_calls: set stop_reason=FINAL_ANSWER and
           final_text to the assistant content; return.
        6. For each tool call: log tool_call, execute through self.tools,
           append a {"role": "tool", "tool_call_id": ..., "content": <JSON>}
           message, log tool_result and the message.
        7. If self.ctx.submitted: set stop_reason=SUBMIT, final_text=
           self.ctx.submission, return.
        """
        if getattr(self,'report_context_pruning',False):
            from .report_context import prune_repeated_results
            self.messages,pruned=prune_repeated_results(self.messages)
            if pruned:
                self.logger.log('context_pruned',method='exact_duplicate_tool_results',items=pruned)
                self.logger.log('context_checkpoint',messages=self.messages,source_sha256='duplicate-results')
        self.messages, compact = maybe_compact(
            self.messages, self.model, self.config.context_max_tokens,
            self.config.context_keep_last,
        )
        if compact is not None:
            self._record_usage(compact, purpose="compaction")
            self.logger.log("compaction", **compact)
            if compact["accepted"]:
                self.logger.log("context_checkpoint", messages=self.messages,
                                source_sha256=compact["source_sha256"])
            reason = self.should_stop()
            if reason is not None:
                self.stop_reason = reason
                return
        self.steps += 1
        response = self.model.chat(self.messages, self.tools.schemas())
        self.finish_reason=response.get('finish_reason')
        self._record_usage(response, purpose="agent")
        message = response["message"]
        self.messages.append(message)
        self.logger.message(message)
        calls = response.get("tool_calls", []) or []
        if not calls:
            self.stop_reason = StopReason.FINAL_ANSWER
            self.final_text = message.get("content") or ""
            return
        image_inputs = []
        for call in calls:
            self.logger.tool_call(call["name"], call["arguments"], call["id"])
            if self.ctx.submitted:
                result = ToolResult(-1, error="skipped: task already submitted")
            elif self.finish_reason=='length':
                result = ToolResult(-1, error='model_output_truncated: response reached generation limit; incomplete action was not executed')
            else:
                result = self.tools.execute(call["name"], call["arguments"], self.ctx)
            self.logger.tool_result(call["id"], result.as_dict())
            observation = {"role": "tool", "tool_call_id": call["id"],
                           "content": json.dumps(result.as_dict(), ensure_ascii=False)}
            self.messages.append(observation)
            self.logger.message(observation)
            if self.ctx.image_inputs_enabled:
                image_inputs.extend(result.images)
        # Finish every paired tool observation before adding a multimodal user
        # message. This preserves the tool protocol when a turn has several calls.
        if image_inputs:
            content = []
            for item in image_inputs:
                content.extend([{'type': 'text', 'text': item['label'] + ' (sha256=' + item['sha256'] + ')'},
                                {'type': 'image_url', 'image_url': {'url': item['url'], 'detail': 'high'}}])
            image_message = {'role': 'user', 'content': content}
            self.messages.append(image_message)
            self.logger.message(image_message)
        if self.ctx.submitted:
            self.stop_reason = StopReason.SUBMIT
            self.final_text = self.ctx.submission

    def _record_usage(self, response: dict, *, purpose: str) -> None:
        self.cost += response.get("cost", 0.0)
        for key in self.usage:
            self.usage[key] += int(response.get("usage", {}).get(key, 0) or 0)
        self.logger.log("model_usage", step=self.steps, purpose=purpose,
                        usage=response.get("usage", {}), cost=response.get("cost", 0.0),
                        cost_currency="USD", usd_cost_known=response.get("usd_cost_known", True), billing=response.get("billing"))

    def should_stop(self) -> StopReason | None:
        if self.stop_reason is not None:
            return self.stop_reason
        if self.ctx.submitted:
            return StopReason.SUBMIT
        if self.config.max_steps and self.steps >= self.config.max_steps:
            return StopReason.MAX_STEPS
        if self.config.max_cost and self.cost >= self.config.max_cost:
            return StopReason.MAX_COST
        if self.config.max_seconds and time.time() - self._started >= self.config.max_seconds:
            return StopReason.MAX_SECONDS
        return None
