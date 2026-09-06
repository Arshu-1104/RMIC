"""
rmic-guard — role-boundary preservation and identity-drift detection for
autonomous LLM agents.

Beginner quickstart (no LLM API key required to see PASS/BLOCK):

    from rmic_guard import RMICContract, ToolRegistry, EnforcementEngine
    from core.planning import PlannedToolCall

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
    )

    tools = ToolRegistry()
    tools.register("web_search", lambda query: {"results": [f"Search results for: {query}"]})

    engine = EnforcementEngine(contract=contract, tools=tools)
    outcome = engine.evaluate_and_maybe_execute(
        PlannedToolCall(tool_name="web_search", arguments={"query": "hello"}, raw_text="hello"),
        recent_ids=[],
    )
    print(outcome.decision)  # "PASS" | "WARN" | "BLOCK" | "NEEDS_RECOVERY" | "PREEMPTIVE_WARN"

With an LLM in the loop:

    from rmic_guard import load_contract, EnforcementEngine, ClaudeReasoning

    contract = load_contract("contracts/financial_agent.json")
    reasoning = ClaudeReasoning()  # reads ANTHROPIC_API_KEY from env
    plan = reasoning.plan_tool_call(user_message, contract=contract, condition="C")
    outcome = engine.evaluate_and_maybe_execute(plan, recent_ids=[])

This package is a stable public import surface over the existing `core`
implementation — nothing here is reimplemented, it's re-exported (plus the
beginner-facing RMICContract.create(...) factory and the SDK exception
hierarchy, which live in core/contract_loader.py and core/exceptions.py
respectively so they stay import-cycle-free).
"""
from __future__ import annotations

from core.contract_loader import (
    DataScope,
    ParameterConstraint,
    RMICContract,
    canonical_contract_dict_for_hash,
    compute_contract_hash,
    create_contract,
    load_contract,
    seal_contract_file,
    verify_contract,
)
from core.enforcement_engine import (
    EnforcementEngine,
    EnforcementMode,
    EnforcementOutcome,
)
from core.exceptions import (
    ContractIntegrityError,
    ContractNotSealedError,
    EnforcementConfigError,
    InvalidContractError,
    RMICGuardError,
    ToolExecutionNotApprovedError,
    ToolNotRegisteredError,
)
from core.ids_engine import IDSEngine
from core.planning import PlannedToolCall
from core.tool_layer import ToolRegistry, ToolResult
from core.validation import validate_contract_dict

# core.reasoning_layer pulls in litellm (an optional "LLM integration"
# dependency — see pyproject.toml's [anthropic]/[groq]/[llm] extras). A
# pure enforcement/contract user (`pip install rmic-guard`, no extras)
# should not be forced to have litellm installed just to import this
# package, so these three names are loaded lazily via module __getattr__
# below instead of at import time. PlannedToolCall itself is litellm-free
# (it lives in core.planning) and is imported eagerly above.
_LAZY_REASONING_NAMES = {"ClaudeReasoning", "GroqReasoning", "ReasoningLayer"}


def __getattr__(name: str):  # PEP 562 lazy attribute access
    if name in _LAZY_REASONING_NAMES:
        try:
            from core import reasoning_layer
        except ImportError as exc:  # pragma: no cover - exercised only without extras
            raise ImportError(
                f"rmic_guard.{name} requires the optional LLM integration dependencies. "
                'Install with: pip install "rmic-guard[llm]" (or [anthropic] / [groq]).'
            ) from exc
        return getattr(reasoning_layer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # contracts — beginner + advanced API
    "RMICContract",
    "create_contract",
    "DataScope",
    "ParameterConstraint",
    "load_contract",
    "seal_contract_file",
    "verify_contract",
    "compute_contract_hash",
    "canonical_contract_dict_for_hash",
    "validate_contract_dict",
    # exceptions
    "RMICGuardError",
    "InvalidContractError",
    "ContractIntegrityError",
    "ContractNotSealedError",
    "ToolNotRegisteredError",
    "ToolExecutionNotApprovedError",
    "EnforcementConfigError",
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
