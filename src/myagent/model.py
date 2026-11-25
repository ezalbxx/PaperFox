from __future__ import annotations

import time
from typing import Any

from .config import Config, PRICES


class ModelConfigError(RuntimeError):
    pass


class OpenAIModel:
    """Thin wrapper around the OpenAI-compatible chat completions API."""

    def __init__(self, config: Config):
        self.config = config
        if not self.config.api_key and self.config.api_auth != 'none':
            raise ModelConfigError(
                "MYAGENT_API_KEY is empty. Copy .env.example to .env and fill your key."
            )
        if not self.config.base_url or not self.config.model:
            raise ModelConfigError("MYAGENT_BASE_URL / MYAGENT_MODEL is empty.")
        if config.buffered:
            return
        try:
            from openai import OpenAI
            import httpx
        except ImportError as exc:  # pragma: no cover - depends on env
            raise ModelConfigError(f"model client dependency unavailable ({exc}); install project dependencies with pip install -e .") from exc
        self._client = OpenAI(base_url=self.config.base_url, api_key=self.config.api_key,
                              timeout=60.0, max_retries=0,
                              http_client=httpx.Client(trust_env=self.config.trust_env, follow_redirects=False))

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = "auto",
    ) -> dict[str, Any]:
        if self.config.buffered:
            return self._buffered_chat(messages, tools, tool_choice)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.chat.completions.create(
                    model=self.config.model,
                    messages=[{k: v for k, v in message.items() if k != 'native_turn'} for message in messages],
                    tools=tools or None,
                    tool_choice=(tool_choice if tools else None),
                    **({} if self.config.provider in ('openai', 'custom') else {'temperature': 0.2}),
                    extra_body=self.config.request_options(),
                )
                return self._normalize(response)
            except Exception as exc:  # noqa: BLE001 - retry only transient errors
                last_error = exc
                status = getattr(exc, "status_code", None)
                if status not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"model call failed: {last_error}")

    def _buffered_chat(self, messages, tools, tool_choice, **options):
        from .model_endpoint import buffered_call

        response, finish, native, known = buffered_call(self.config, messages, tools, tool_choice, **options)
        result = self._normalize(response)
        if native is not None:
            result['message']['native_turn'] = native
        return {**result, 'finish_reason': finish, 'usage_known': known}

    def _normalize(self, response: Any) -> dict[str, Any]:
        choice = response.choices[0]
        msg = choice.message
        tool_calls: list[dict] = []
        assistant: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning is not None:
            assistant["reasoning_content"] = reasoning
        if msg.tool_calls:
            assistant["tool_calls"] = []
            for call in msg.tool_calls:
                item = {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                assistant["tool_calls"].append(item)
                tool_calls.append(
                    {
                        "id": call.id,
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    }
                )
        usage = {
            "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
            "prompt_cache_hit_tokens": getattr(response.usage, "prompt_cache_hit_tokens", 0) or 0,
            "prompt_cache_miss_tokens": getattr(response.usage, "prompt_cache_miss_tokens", 0) or 0,
        }
        details=getattr(response.usage, "prompt_tokens_details", None)
        if self.config.provider == "qianwen":
            usage["prompt_cache_hit_tokens"]=int(getattr(details,"cached_tokens",0) or 0)
            usage["prompt_cache_miss_tokens"]=max(0,usage["prompt_tokens"]-usage["prompt_cache_hit_tokens"])
        billing=self.config.billing_details(usage)
        return {
            "billing": billing,
            "usd_cost_known": billing is None and self.config.model in PRICES,
            "message": assistant,
            "tool_calls": tool_calls,
            "usage": usage,
            "cost": self.config.cost_of(usage),
            "raw": response.model_dump() if hasattr(response, "model_dump") else {},
        }
