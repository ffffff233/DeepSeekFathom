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
    deliberation_passes: int = 0
    api_thinking: bool = True
    reasoning_effort: str | None = None

    @classmethod
    def resolve(cls, mode: str) -> "ThinkingMode":
        modes = {
            "off": cls("off", "deepseek-v4-flash", 4096, "Answer directly. Avoid extended reasoning.", 0, False, None),
            "instant": cls("instant", "deepseek-v4-flash", 8192, "Use the fastest practical response. Ask for tools only when needed.", 0, False, None),
            "fast": cls("fast", "deepseek-v4-flash", 32768, "Use quick reasoning and prefer cheap exploratory tool calls.", 0, True, "high"),
            "standard": cls("standard", "deepseek-v4-flash", 65536, "Use normal task reasoning with concise checks.", 0, True, "high"),
            "balanced": cls("balanced", "deepseek-v4-pro", 128000, "Use measured reasoning. Plan briefly before risky edits.", 1, True, "high"),
            "careful": cls("careful", "deepseek-v4-pro", 192000, "Use careful reasoning and verify assumptions before edits.", 1, True, "high"),
            "deep": cls("deep", "deepseek-v4-pro", 256000, "Think deeply about tradeoffs, hidden state, tests, and failure modes.", 2, True, "high"),
            "deeper": cls("deeper", "deepseek-v4-pro", 320000, "Use deeper multi-step reasoning for complex debugging and architecture.", 2, True, "max"),
            "max": cls("max", "deepseek-v4-pro", 384000, "Use maximum practical reasoning for ambiguous multi-step engineering work.", 3, True, "max"),
            "ultra": cls("ultra", "deepseek-v4-pro", 384000, "Use the largest supported output and internal thinking budget.", 4, True, "max"),
        }
        try:
            return modes[mode]
        except KeyError as exc:
            names = ", ".join(sorted(modes))
            raise ValueError(f"thinking mode must be one of: {names}") from exc

    @classmethod
    def names(cls) -> list[str]:
        return ["off", "instant", "fast", "standard", "balanced", "careful", "deep", "deeper", "max", "ultra"]
