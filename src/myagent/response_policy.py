"""Per-turn response depth is independent of long-running goal mode."""
from dataclasses import dataclass, asdict
import re

DEPTHS = ("auto", "quick", "balanced", "deep")


@dataclass(frozen=True)
class ResponsePolicy:
    depth: str
    reason: str
    thinking: bool
    effort: str

    def as_dict(self):
        return asdict(self)

    def instruction(self):
        return {
            "quick": "Answer this small question directly in the first paragraph. Use existing context first. If a fact needs a file, read only that relevant file/section. Do not turn a question into implementation or broad research. State uncertainty rather than inventing a number.",
            "balanced": "Complete the scoped request with a useful result. Read relevant evidence as needed, perform necessary checks once, then deliver.",
            "deep": "The user requests exploration. Investigate relevant primary evidence, compare alternatives, explain mechanisms and limitations. Show useful findings as they emerge; depth is not permission to expand the task or repeat audits.",
        }[self.depth]


def choose_policy(text, mode, preference="auto"):
    if preference not in DEPTHS:
        raise ValueError("depth must be auto, quick, balanced or deep")
    if preference != "auto":
        depth, reason = preference, "explicit response-depth selection"
    elif re.search(r"深入(?:探索|研究|分析|调查)|深度(?:研究|分析|思考)|系统(?:性)?(?:调研|研究)|详细调研|deep research|in.depth", text, re.I):
        depth, reason = "deep", "explicit exploration request"
    elif mode == "consult" or (len(text) <= 180 and re.search(r"[?？]|为什么|是什么|多少|怎么回事|区别|解释一下|what |why |how much", text, re.I)):
        depth, reason = "quick", "consultation or bounded question"
    else:
        depth, reason = "balanced", "scoped execution or goal continuation"
    return ResponsePolicy(depth, reason, depth == "deep", "high" if depth == "deep" else "low")
