from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROVIDERS: dict[str, dict[str, str]] = {
    "qianwen": {"base_url": "https://maas.qianwenaiapi.com/compatible-mode/v1", "model": "deepseek-v4.1-flash-1017"},
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.8-flash",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-flash",
    },
    "custom": {
        "base_url": "",
        "model": "",
    },
}

# USD per 1M tokens, only for the two presets. Unknown models show tokens, cost 0.
PRICES: dict[str, tuple[float, float]] = {
    "qwen3.8-flash": (0.8, 2.7),
    # 2026-10-19 official peak USD rates. Conservative estimate: off-peak is lower.
    "deepseek-flash": (0.3, 1.2),
}


def load_dotenv(path: Path) -> None:
    """Tiny .env loader. Does not override already-exported variables."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass
class Config:
    provider: str = "dashscope"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    api_protocol: str = "chat"
    api_auth: str = "bearer"
    api_version: str = ""
    buffered: bool = False
    max_steps: int = 20
    max_cost: float = 0.5
    max_seconds: int = 300
    timeout_s: int = 120
    max_output_chars: int = 8000
    workspace: Path = field(default_factory=Path.cwd)
    python_exe: str = field(default_factory=lambda: sys.executable)
    shell_backend: str = "auto"
    trust_env: bool = True
    session_dir: Path | None = None
    context_max_tokens: int = 12000
    context_keep_last: int = 6
    execution_policy: str = "trusted"
    skill_dirs: tuple[Path, ...] = ()
    personal_tools: str = "skills"
    figure_model: str = ""
    figure_supports_images: bool = False

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        if self.session_dir is None:
            self.session_dir = self.workspace / ".myagent" / "sessions"
        else:
            self.session_dir = Path(self.session_dir).resolve()
        preset = PROVIDERS.get(self.provider, PROVIDERS["custom"])
        self.base_url = self.base_url or preset["base_url"]
        self.model = self.model or preset["model"]
        if self.api_protocol != "chat" or self.api_auth != "bearer" or self.api_version:
            self.buffered = True
        if self.execution_policy not in ("guarded", "trusted"):
            raise ValueError("execution_policy must be guarded or trusted")
        self.skill_dirs = tuple(Path(p).resolve() for p in self.skill_dirs)
        if self.personal_tools not in ("skills", "course"):
            raise ValueError("personal_tools must be skills or course")

    @classmethod
    def from_env(cls, workspace: Path | str | None = None, **overrides) -> "Config":
        ws = Path(workspace).resolve() if workspace else Path.cwd().resolve()
        from .paperfox_setup import model_settings, settings_path
        portable = settings_path() is not None
        if not portable:
            load_dotenv(ws / ".env")
            if Path.cwd().resolve() != ws:
                load_dotenv(Path.cwd() / ".env")
            load_dotenv(Path(__file__).resolve().parents[3] / ".env")
        provider = os.getenv("MYAGENT_PROVIDER", "dashscope").strip() or "dashscope"
        preset = PROVIDERS.get(provider, PROVIDERS["custom"])
        data = {
            "provider": provider,
            "base_url": os.getenv("MYAGENT_BASE_URL", "").strip() or preset["base_url"],
            "api_key": os.getenv("MYAGENT_API_KEY", "").strip(),
            "model": os.getenv("MYAGENT_MODEL", "").strip() or preset["model"],
            "max_steps": _env_int("MYAGENT_MAX_STEPS", 20),
            "max_cost": _env_float("MYAGENT_MAX_COST", 0.5),
            "max_seconds": _env_int("MYAGENT_MAX_SECONDS", 300),
            "timeout_s": _env_int("MYAGENT_TIMEOUT_S", 120),
            "max_output_chars": _env_int("MYAGENT_MAX_OUTPUT_CHARS", 8000),
            "workspace": ws,
            "python_exe": os.getenv("MYAGENT_PYTHON", "").strip() or sys.executable,
            "shell_backend": os.getenv("MYAGENT_SHELL_BACKEND", "auto").strip() or "auto",
            "trust_env": os.getenv("MYAGENT_TRUST_ENV", "true").lower() not in ("0", "false", "no"),
            "context_max_tokens": _env_int("MYAGENT_CONTEXT_MAX_TOKENS", 12000),
            "context_keep_last": _env_int("MYAGENT_CONTEXT_KEEP_LAST", 6),
            "execution_policy": os.getenv("MYAGENT_EXECUTION_POLICY", "guarded"),
            "figure_model": os.getenv("MYAGENT_FIGURE_MODEL", "").strip(),
            "figure_supports_images": os.getenv("MYAGENT_FIGURE_SUPPORTS_IMAGES", "false").lower() in ("1", "true", "yes"),
        }
        if portable:
            data.update(model_settings(), figure_model="", figure_supports_images=False)
        data.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**data)

    def request_options(self, *, thinking=False, effort=None):
        if self.provider == "deepseek":
            return {"thinking": {"type": "enabled" if thinking else "disabled"},
                    **({"reasoning_effort": effort} if thinking and effort else {})}
        if self.provider == "qianwen":
            return {"enable_thinking": bool(thinking),
                    **({"reasoning_effort": effort} if thinking and effort else {})}
        return {}

    def billing_details(self, usage):
        if self.provider != "qianwen" or self.model not in ("deepseek-v4.1-flash", "deepseek-v4.1-flash-1017"):
            return None
        from datetime import datetime,timezone,timedelta
        stamp=datetime.now(timezone(timedelta(hours=8)))
        peak=8 <= stamp.hour < 22
        rates=(2.0,0.2,8.0) if peak else (1.0,0.1,4.0)
        prompt=int(usage.get("prompt_tokens",0) or 0);output=int(usage.get("completion_tokens",0) or 0)
        cached=min(prompt,int(usage.get("prompt_cache_hit_tokens",0) or 0))
        return {"currency":"CNY","estimated_amount":((prompt-cached)*rates[0]+cached*rates[1]+output*rates[2])/1e6,
                "rates_per_million":{"input":rates[0],"cached_input":rates[1],"output":rates[2]},
                "period":"peak" if peak else "off_peak","at":stamp.isoformat(),
                "source":"https://platform.qianwenai.com/docs/models/deepseek-v4-1-flash",
                "price_version":"2026-11-09","notice":"Listed rate estimate; excludes account promotions/free quota and is not an invoice. Not converted to USD."}

    def cost_of(self, usage: dict[str, int]) -> float:
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        price_in, price_out = PRICES.get(self.model, (0.0, 0.0))
        if self.model == "deepseek-flash":
            hits = min(prompt, int(usage.get("prompt_cache_hit_tokens", 0) or 0))
            return ((prompt - hits) * price_in + hits * 0.006 + completion * price_out) / 1_000_000
        return (prompt * price_in + completion * price_out) / 1_000_000
