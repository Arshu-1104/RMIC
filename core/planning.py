"""Planning data model — the tool-call plan produced by any reasoning
backend, plus pure-Python JSON parsing/validation of that plan.

Deliberately has NO dependency on litellm/anthropic/groq: PlannedToolCall
is consumed by core.enforcement_engine (core SDK functionality) and must
stay importable without the optional LLM integration extras installed.
Only core.reasoning_layer (which talks to actual model APIs) depends on
litellm; it imports these primitives from here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

__all__ = ["PlannedToolCall", "ResponseValidator", "parse_planned_json"]


@dataclass
class PlannedToolCall:
    """Structured plan produced by the model before tool execution."""

    tool_name: str
    arguments: dict[str, Any]
    raw_text: str
    data_categories_accessed: tuple[str, ...] = ()


def parse_planned_json(text: str) -> PlannedToolCall:
    """Best-effort parse of model output into PlannedToolCall."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        return PlannedToolCall("refused", {}, text, ())
    tool_name = str(obj.get("tool_name", "")).strip()
    args = obj.get("arguments") or {}
    if not isinstance(args, dict):
        args = {}
    dca = obj.get("data_categories_accessed") or []
    cats = (dca,) if isinstance(dca, str) else tuple(str(x) for x in dca)
    return PlannedToolCall(
        tool_name=tool_name,
        arguments={k: v for k, v in args.items()},
        raw_text=text,
        data_categories_accessed=cats,
    )


class ResponseValidator:
    """Validate and coerce model JSON output before creating PlannedToolCall."""

    CORRECTION_PROMPT = (
        "Your previous response was not valid JSON or had wrong format.\n"
        "You MUST respond with ONLY this JSON structure, no other text:\n"
        '{\n  "tool_name": "<exact tool name to call>",\n'
        '  "arguments": {},\n  "data_categories_accessed": []\n}\n'
        "Do not add explanations, markdown, or any text outside the JSON object."
    )

    _BAD_TOOL_NAMES = {"refused", "refusal", "decline", "error", ""}

    @classmethod
    def validate_and_parse(cls, text: str, context: str) -> tuple[PlannedToolCall, bool]:
        _ = context
        plan = parse_planned_json(text)
        return (plan, True) if cls._is_valid(plan) else (PlannedToolCall("refused", {}, text, ()), False)

    @classmethod
    def _is_valid(cls, plan: PlannedToolCall) -> bool:
        if not isinstance(plan.tool_name, str):
            return False
        if plan.tool_name.strip().lower() in cls._BAD_TOOL_NAMES:
            return False
        if not isinstance(plan.arguments, dict):
            return False
        if not isinstance(plan.data_categories_accessed, tuple):
            return False
        return True
