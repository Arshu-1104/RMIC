"""RMIC-Guard quickstart.

Runs completely offline - no LLM API key, no network call, no embedding
model download. It proves the core promise of RMIC-Guard: a forbidden tool
call is BLOCKed before it ever reaches your tool's code.

Run it with either:

    pip install -e .
    python examples/quickstart.py

or, once published:

    pip install rmic-guard
    python examples/quickstart.py

For semantic identity-drift detection (the IDS score, not just hard
tool-name rules) see examples/identity_drift.py -- that one needs a local
embedding model, downloaded once on first use. For talking to a real LLM
to *produce* the tool-call plan (rather than constructing it directly, as
below), see examples/basic_enforcement.py and the README.
"""

from __future__ import annotations

from core.planning import PlannedToolCall
from rmic_guard import EnforcementEngine, RMICContract, ToolRegistry


def main() -> None:
    print("RMIC-GUARD QUICKSTART")
    print()

    print("Creating contract...")
    contract = RMICContract.create(
        agent_id="research-agent",
        role_name="Research Agent",
        sector="research",
        role_description="Performs safe research tasks.",
        semantic_anchors=[
            "I perform research and information gathering.",
            "I do not perform destructive or unauthorized actions.",
        ],
        allowed_actions=["web_search"],
        forbidden_actions=["delete_data"],
        # No network / model download needed for this demo: hard-rule
        # enforcement (forbidden tool names, parameter bounds, data scope)
        # doesn't use semantic embeddings at all. See identity_drift.py for
        # the embedding-backed path.
        require_embedding=False,
    )
    print("Contract created")
    print("Contract validated")
    print("Contract sealed")
    print(f"  contract_hash: {contract.contract_hash[:16]}...")
    print()

    print("Registering tools...")

    def web_search(query: str) -> dict:
        return {"results": [f"Search results for: {query}"]}

    def delete_data(path: str) -> dict:
        return {"deleted": path}

    tools = ToolRegistry()
    tools.register("web_search", web_search)
    tools.register("delete_data", delete_data)
    print("web_search registered")
    print("delete_data registered")
    print()

    engine = EnforcementEngine(contract=contract, tools=tools)

    print("-" * 34)
    print("TEST 1 - SAFE ACTION")
    print("-" * 34)
    print()
    safe_plan = PlannedToolCall(
        tool_name="web_search",
        arguments={"query": "identity drift in LLM agents"},
        raw_text="search for papers on identity drift",
    )
    safe_outcome = engine.evaluate_and_maybe_execute(
        safe_plan, recent_ids=[], enforcement_mode="hard_rules_only"
    )
    print("Tool: web_search")
    print(f"Decision: {safe_outcome.decision}")
    print(f"Execution: {'ALLOWED' if safe_outcome.tool_result is not None else 'PREVENTED'}")
    if safe_outcome.tool_result is not None:
        print(f"Result: {safe_outcome.tool_result.data}")
    print()

    print("-" * 34)
    print("TEST 2 - FORBIDDEN ACTION")
    print("-" * 34)
    print()
    forbidden_plan = PlannedToolCall(
        tool_name="delete_data",
        arguments={"path": "/prod/customer_db"},
        raw_text="delete the production customer database",
    )
    forbidden_outcome = engine.evaluate_and_maybe_execute(
        forbidden_plan, recent_ids=[], enforcement_mode="hard_rules_only"
    )
    print("Tool: delete_data")
    print(f"Decision: {forbidden_outcome.decision}")
    print(f"Reason: {forbidden_outcome.hard_rule_violation}")
    print(f"Execution: {'ALLOWED' if forbidden_outcome.tool_result is not None else 'PREVENTED'}")
    print()

    assert safe_outcome.decision == "PASS"
    assert forbidden_outcome.decision == "BLOCK"
    assert forbidden_outcome.tool_result is None
    print("Quickstart complete: safe action PASSed, forbidden action was BLOCKed and never executed.")


if __name__ == "__main__":
    main()
