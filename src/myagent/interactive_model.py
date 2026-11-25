"""Streaming adapter for interactive use; the course's synchronous model stays intact."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from .model import OpenAIModel


class ResponseCancelled(Exception):
    def __init__(self, response: dict):
        super().__init__("response interrupted; server-side usage may be incomplete")
        self.response = response


class StreamingModel(OpenAIModel):
    def __init__(self, config, emit=None):
        super().__init__(config)
        self.emit = emit or (lambda kind, **data: None)
        self.cancel_event = threading.Event()
        self.deadline = None
        self._stream = None
        self.response_policy = None

    def set_response_policy(self, policy):
        self.response_policy = policy

    def cancel(self):
        self.cancel_event.set()
        stream = self._stream
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

    def chat(self, messages, tools=None, tool_choice="auto"):
        text, calls, usage = [], {}, None
        finish_reason = None
        compacting = bool(messages and str(messages[0].get("content", "")).startswith(
            "Summarize conversation evidence in at most"))
        started = time.monotonic()
        emitted = False
        reasoning, first_answer = [], False
        policy = getattr(self, "response_policy", None)
        thinking = bool(policy and policy.thinking and not compacting)
        self.emit("context_preparing" if compacting else "api_wait")
        try:
            for attempt in range(3):
                if self.cancel_event.is_set():
                    raise ResponseCancelled(self._result(text, calls, usage))
                remaining = self.deadline - time.monotonic() if self.deadline else 60.0
                if remaining <= 0:
                    raise TimeoutError("turn deadline reached before model call")
                try:
                    self._stream = self._client.chat.completions.create(
                        model=self.config.model, messages=messages, tools=tools or None,
                        tool_choice=tool_choice if tools else None, temperature=0.2,
                        stream=True, stream_options={"include_usage": True},
                        **({'parallel_tool_calls': False} if getattr(self, 'single_tool_calls', False) else {}),
                        timeout=min(60.0, remaining), max_tokens=getattr(self, 'output_token_limit', 8192 if thinking else 4096),
                        extra_body=self.config.request_options(thinking=thinking, effort=policy.effort if thinking else None),
                    )
                    for chunk in self._stream:
                        if self.cancel_event.is_set():
                            raise ResponseCancelled(self._result(text, calls, usage))
                        if self.deadline and time.monotonic() >= self.deadline:
                            raise TimeoutError("turn deadline reached during response")
                        if not emitted:
                            self.emit("api_first_event", seconds=time.monotonic()-started)
                            emitted = True
                        if chunk.usage is not None:
                            usage = chunk.usage
                        for choice in chunk.choices:
                            if getattr(choice,'finish_reason',None):finish_reason=choice.finish_reason
                            delta = choice.delta
                            thought = getattr(delta, "reasoning_content", None)
                            if thought:
                                if not reasoning:
                                    self.emit("model_reasoning", seconds=time.monotonic()-started)
                                reasoning.append(thought)
                            if delta.content:
                                if not first_answer:
                                    self.emit("first_answer", seconds=time.monotonic()-started)
                                    first_answer = True
                                text.append(delta.content)
                                if not compacting:
                                    self.emit("answer_delta", text=delta.content)
                            for call in delta.tool_calls or []:
                                target = calls.setdefault(call.index, {"id": "", "name": "", "arguments": ""})
                                if call.id:
                                    target["id"] = call.id
                                if call.function:
                                    target["name"] += call.function.name or ""
                                    target["arguments"] += call.function.arguments or ""
                    break
                except ResponseCancelled:
                    raise
                except Exception as exc:
                    if self.cancel_event.is_set():
                        raise ResponseCancelled(self._result(text, calls, usage)) from exc
                    transient = (getattr(exc, "status_code", None) in (429, 500, 502, 503, 504)
                                 or type(exc).__name__ in ('APIConnectionError','APITimeoutError','ConnectError','ConnectTimeout'))
                    if emitted or not transient or attempt == 2:
                        # Partial generation has no reliable billable usage; do not silently retry it.
                        if emitted:
                            self.emit("usage_unknown", reason="stream interrupted before final usage")
                        raise
                    self.emit("api_retry", attempt=attempt+1, reason=type(exc).__name__)
                    if self.cancel_event.wait(1.5*(attempt+1)):
                        raise ResponseCancelled(self._result(text, calls, usage))
                finally:
                    if self._stream is not None:
                        self._stream.close()
                        self._stream = None
            if self.cancel_event.is_set():
                raise ResponseCancelled(self._result(text, calls, usage))
            result = self._result(text, calls, usage, "".join(reasoning) if thinking else None)
            result['finish_reason']=finish_reason
            self.emit("api_end", seconds=time.monotonic()-started, usage_known=usage is not None,
                      reasoning_chars=sum(map(len, reasoning)), depth=policy.depth if policy else "balanced")
            return result
        finally:
            self._stream = None

    def _result(self, text, calls, usage, reasoning=None):
        message = SimpleNamespace(content="".join(text), reasoning_content=reasoning, tool_calls=[
            SimpleNamespace(id=item["id"], function=SimpleNamespace(name=item["name"], arguments=item["arguments"]))
            for _, item in sorted(calls.items())])
        result = self._normalize(SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage))
        result["usage_known"] = usage is not None
        return result
