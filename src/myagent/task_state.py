"""Persistent user goals, independent of an individual answer or process."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GoalState:
    objective: str
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    status: str = "running"
    summary: str = ""
    plan: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    jobs: dict = field(default_factory=dict)
    steps: int = 0
    cost: float = 0.0
    elapsed_seconds: float = 0.0
    max_steps: int = 100
    max_cost: float = 0.5
    max_seconds: float = 3600
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    stop_reason: str = ""
    tokens: int = 0
    max_tokens: int = 0
    authorization: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)

    def limit_reason(self) -> str | None:
        if self.max_tokens and self.tokens >= self.max_tokens:
            return "MaxTokens"
        if self.max_steps and self.steps >= self.max_steps:
            return "MaxSteps"
        if self.max_cost and self.cost >= self.max_cost:
            return "MaxCost"
        if self.max_seconds and self.elapsed_seconds >= self.max_seconds:
            return "MaxSeconds"
        return None
