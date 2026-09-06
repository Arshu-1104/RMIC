"""A slightly larger enforcement walkthrough: multiple tools, a parameter
constraint, and a data-scope restriction -- still fully offline
(enforcement_mode="hard_rules_only", no embedding model needed).

    python examples/basic_enforcement.py
"""

from __future__ import annotations

from core.planning import PlannedToolCall
from rmic_guard import EnforcementEngine, RMICContract, ToolRegistry


def main() -> None:
    contract = RMICContract.create(
        agent_id="finance-assistant",
        role_name="Finance Assistant",
        sector="finance",
        role_description="Looks up account balances and processes small refunds.",
        semantic_anchors=[
            "I look up account balances for customers.",
            "I process refunds within my approval limit.",
        ],
        allowed_actions=["get_balance", "issue_refund"],
        forbidden_actions=["wire_transfer"],
        parameter_constraints={
            "amount": {"min": 0, "max": 500, "type": "float"},
        },
        data_scope={
            "accessible": ["account_balance", "transaction_history"],
            "prohibited": ["ssn", "full_card_number"],
        },
        require_embedding=False,
    )

    tools = ToolRegistry()
    tools.register("get_balance", lambda account_id: {"balance": 1240.55})
    tools.register("issue_refund", lambda account_id, amount: {"refunded": amount})
    tools.register("wire_transfer", lambda account_id, amount, destination: {"sent": amount})

    engine = EnforcementEngine(contract=contract, tools=tools)

    scenarios = [
        (
            "Allowed tool, valid amount",
            PlannedToolCall("issue_refund", {"account_id": "A1", "amount": 45.0}, "refund $45"),
        ),
        (
            "Allowed tool, amount over the $500 limit",
            PlannedToolCall("issue_refund", {"account_id": "A1", "amount": 5000.0}, "refund $5000"),
        ),
        (
            "Forbidden tool by name",
            PlannedToolCall("wire_transfer", {"account_id": "A1", "amount": 100.0, "destination": "X"}, "wire $100"),
        ),
        (
            "Allowed tool, but touches prohibited data",
            PlannedToolCall(
                "get_balance", {"account_id": "A1"}, "look up their SSN",
                data_categories_accessed=("ssn",),
            ),
        ),
    ]

    for label, plan in scenarios:
        outcome = engine.evaluate_and_maybe_execute(plan, recent_ids=[], enforcement_mode="hard_rules_only")
        print(f"{label}")
        print(f"  tool={plan.tool_name} decision={outcome.decision} reason={outcome.hard_rule_violation}")
        print()


if __name__ == "__main__":
    main()
