"""
Minimal end-to-end example of the rmic-guard SDK.

Run from the repo root (needs ANTHROPIC_API_KEY or GROQ_API_KEY set,
and a contract file — this uses the bundled financial_agent.json):

    python examples/quickstart.py
"""
from __future__ import annotations

from rmic_guard import EnforcementEngine, GroqReasoning, load_contract


class DemoToolRegistry:
    """Minimal stand-in ToolRegistry for this example — replace with your
    real tool implementations. See core/tool_layer.py for the interface."""

    def issue_approval_token(self):
        return None

    def execute(self, *args, **kwargs):
        print(f"[demo] would execute tool call: args={args} kwargs={kwargs}")
        return None


def main() -> None:
    contract = load_contract("contracts/financial_agent.json", verify_hash=False)
    reasoning = GroqReasoning()  # reads GROQ_API_KEY from the environment

    user_message = "What's my current account balance?"
    plan = reasoning.plan_tool_call(user_message, contract=contract, condition="C")
    print(f"Planned tool call: {plan.tool_name!r}  args={plan.arguments}")

    engine = EnforcementEngine(contract=contract, tools=DemoToolRegistry(), ledger=None)
    outcome = engine.evaluate_and_maybe_execute(
        plan,
        recent_ids=[],
        drift_type=None,
        execute_tool=False,  # set True once DemoToolRegistry does something real
        enforcement_mode="full",
    )

    print(f"Decision: {outcome.decision}")
    print(f"IDS score: {outcome.ids_score:.3f}")
    print(f"Hard-rule violation: {outcome.hard_rule_violation}")


if __name__ == "__main__":
    main()