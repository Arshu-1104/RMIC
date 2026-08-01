"""
baselines/diagnose_legitimate.py

--test mode in experiment/runner.py slices the combined prompt bundle with
prompt_bundle[:3] BEFORE any category filtering — and role_drift prompts sit
first in that bundle, so --test never actually includes any legitimate/benign
prompts. That made it impossible to cheaply check whether the FPR=1.0 bug was
fixed without running (and paying for) a full experiment.

This script tests a handful of legitimate prompts directly against
B_prompt_contract and C_rmic_middleware for one role, mirroring exactly what
experiment/runner.py does for each condition, without touching the database
or running the rest of the prompt set.

Run:
    python -m baselines.diagnose_legitimate --model groq/llama-3.3-70b-versatile
    python -m baselines.diagnose_legitimate --model groq/llama-3.3-70b-versatile --role financial_agent --n 5

--model lets you pick the model explicitly (bypassing config.yaml's default
provider) — use a groq/... model if your Anthropic quota is exhausted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.enforcement_engine import EnforcementEngine
from core.reasoning_layer import ClaudeReasoning, GroqReasoning
from experiment.runner import load_contract


def load_legitimate_prompts(role: str, n: int) -> list[str]:
    with open(Path("prompts") / "legitimate.json", encoding="utf-8") as f:
        data = json.load(f)
    prompts = list(data.get("prompts", []))
    role_specific = data.get("role_specific", {}).get(role, [])
    combined = (prompts + role_specific)[:n]
    return combined


def build_reasoning_layer(model: str):
    if model.startswith("groq/"):
        return GroqReasoning(model_name=model)
    return ClaudeReasoning(model_name=model)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cheaply test legitimate prompts against B and C_rmic_middleware.")
    parser.add_argument("--role", default="financial_agent")
    parser.add_argument("--n", type=int, default=5)
    parser.add_argument(
        "--model", default="groq/llama-3.3-70b-versatile",
        help="Model to test with, e.g. groq/llama-3.3-70b-versatile or anthropic/claude-haiku-4-5. "
             "Defaults to Groq so this doesn't touch your Anthropic quota.",
    )
    args = parser.parse_args()

    contract = load_contract(args.role)
    reasoning_layer = build_reasoning_layer(args.model)
    prompts = load_legitimate_prompts(args.role, args.n)

    if not prompts:
        print(f"No legitimate prompts found for role={args.role!r}. Check prompts/legitimate.json.")
        return

    print(f"Testing {len(prompts)} legitimate prompts for role={args.role!r} using model={args.model!r}\n")

    for i, user_message in enumerate(prompts, 1):
        print("=" * 70)
        print(f"[{i}] prompt: {user_message}")

        # --- Condition B: prompt-only, no external enforcement ---
        plan_b = reasoning_layer.plan_tool_call(user_message, contract=contract, condition="B")
        print(f"    B_prompt_contract -> tool_name={plan_b.tool_name!r}  "
              f"raw_text={plan_b.raw_text[:120]!r}")

        # --- Condition C: full middleware (hard rules + IDS) ---
        plan_c = reasoning_layer.plan_tool_call(user_message, contract=contract, condition="C")
        engine = EnforcementEngine(contract=contract, tools=_NullToolRegistry(), ledger=None)
        try:
            outcome = engine.evaluate_and_maybe_execute(
                plan_c, recent_ids=[], drift_type=None, execute_tool=False, enforcement_mode="full",
            )
            print(f"    C_rmic_middleware -> tool_name={plan_c.tool_name!r}  "
                  f"decision={outcome.decision}  hard_rule_violation={outcome.hard_rule_violation}  "
                  f"ids_score={outcome.ids_score:.3f}")
        except Exception as e:
            print(f"    C_rmic_middleware -> ERROR: {e}")

    print("=" * 70)


class _NullToolRegistry:
    """Stand-in ToolRegistry — we never execute_tool=True here, so this just
    needs to satisfy EnforcementEngine's constructor without real tool wiring."""

    def issue_approval_token(self):
        return None

    def execute(self, *args, **kwargs):
        raise RuntimeError("execute_tool should be False in this diagnostic")


if __name__ == "__main__":
    main()