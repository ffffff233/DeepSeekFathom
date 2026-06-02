from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalPolicy:
    name: str
    allow_read: bool
    allow_write: bool
    allow_shell: bool
    allow_network: bool
    require_confirmation: bool

    @classmethod
    def from_mode(cls, mode: str) -> "ApprovalPolicy":
        policies = {
            "plan": cls("plan", True, False, False, False, False),
            "review": cls("review", True, False, True, False, True),
            "agent": cls("agent", True, True, True, False, True),
            "trusted": cls("trusted", True, True, True, True, True),
            "yolo": cls("yolo", True, True, True, True, False),
            "root": cls("root", True, True, True, True, False),
        }
        try:
            return policies[mode]
        except KeyError as exc:
            names = ", ".join(sorted(policies))
            raise ValueError(f"mode must be one of: {names}") from exc


@dataclass(frozen=True)
class ThinkingMode:
    name: str
    model_hint: str
    max_tokens: int
    system_hint: str

    @classmethod
    def resolve(cls, mode: str) -> "ThinkingMode":
        modes = {
            "off": cls("off", "deepseek-v4-flash", 1024, "Answer directly. Avoid extended reasoning."),
            "fast": cls("fast", "deepseek-v4-flash", 2048, "Use quick reasoning and prefer cheap exploratory tool calls."),
            "balanced": cls("balanced", "deepseek-v4-pro", 4096, "Use measured reasoning. Plan briefly before risky edits."),
            "deep": cls("deep", "deepseek-v4-pro", 8192, "Think deeply about tradeoffs, hidden state, tests, and failure modes."),
            "max": cls("max", "deepseek-v4-pro", 12000, "Use maximum practical reasoning for ambiguous multi-step engineering work."),
        }
        try:
            return modes[mode]
        except KeyError as exc:
            names = ", ".join(sorted(modes))
            raise ValueError(f"thinking mode must be one of: {names}") from exc
