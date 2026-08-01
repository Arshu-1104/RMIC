"""
rmic-guard — role-boundary preservation and identity-drift detection for
autonomous LLM agents.

Quickstart:

    from rmic_guard import load_contract, EnforcementEngine, ClaudeReasoning

    contract = load_contract("contracts/financial_agent.json")
    reasoning = ClaudeReasoning()  # reads ANTHROPIC_API_KEY from env
    engine = EnforcementEngine(contract=contract, tools=my_tool_registry, ledger=None)

    plan = reasoning.plan_tool_call(user_message, contract=contract, condition="C")
    outcome = engine.evaluate_and_maybe_execute(
        plan, recent_ids=[], drift_type=None, execute_tool=True,
        enforcement_mode="full",
    )
    print(outcome.decision)  # "PASS" | "WARN" | "BLOCK" | "NEEDS_RECOVERY" | "PREEMPTIVE_WARN"

This package is a thin, stable public import surface over the existing
`core` implementation — nothing here is reimplemented, it's re-exported.
"""
from __future__ import annotations

from core.contract_loader import (
    DataScope,
    ParameterConstraint,
    RMICContract,
    load_contract,
    seal_contract_file,
)
from core.enforcement_engine import (
    EnforcementEngine,
    EnforcementMode,
    EnforcementOutcome,
)
from core.ids_engine import IDSEngine
from core.reasoning_layer import (
    ClaudeReasoning,
    GroqReasoning,
    PlannedToolCall,
    ReasoningLayer,
)
from core.tool_layer import ToolRegistry, ToolResult

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # contracts
    "RMICContract",
    "DataScope",
    "ParameterConstraint",
    "load_contract",
    "seal_contract_file",
    # enforcement
    "EnforcementEngine",
    "EnforcementMode",
    "EnforcementOutcome",
    # drift detection
    "IDSEngine",
    # reasoning / planning
    "ReasoningLayer",
    "ClaudeReasoning",
    "GroqReasoning",
    "PlannedToolCall",
    # tools
    "ToolRegistry",
    "ToolResult",
]