"""
rmic-guard — role-boundary preservation and identity-drift detection for
autonomous LLM agents.

Quickstart (one object, one call):

    from rmic_guard import Guard

    guard = Guard("contracts/bank_bot.json")        # load + validate + seal + verify

    @guard.tool
    def transfer_funds(amount: float, to: str):
        return {"sent": amount, "to": to}

    result = guard.check("transfer_funds", amount=500, to="4321", message="pay rent")
    print(result.allowed, result.decision, result.reason, result.output)

    # Let an LLM plan the call (pip install "rmic-guard[llm]"):
    result = guard.run("Transfer $500 to 4321 for rent", llm="groq/llama-3.3-70b-versatile")

By default Guard enforces the hard rules only (forbidden tools, parameter
bounds, data scope) with no embedding model and no network. semantic=True adds
semantic identity-drift detection; it is EXPERIMENTAL (on the current scoring
attacks do not score higher than legitimate requests, see
experiment/ids_calibration_investigation/post_sep22_threshold_calibration.md)
and its first use downloads the BAAI/bge-small-en-v1.5 embedding model once.

Lower-level API (what Guard is built on, still fully supported):

    from rmic_guard import RMICContract, ToolRegistry, EnforcementEngine, PlannedToolCall

    contract = RMICContract.create(
        agent_id="research-agent",
        role_name="Research Agent",
        sector="research",
        semantic_anchors=["I perform research and information gathering."],
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
    print(outcome.decision)  # "PASS" | "BLOCK" | "NEEDS_RECOVERY" | "PREEMPTIVE_WARN"

Everything public is importable from `rmic_guard` directly. The
implementation lives in the private `rmic_guard._core` / `rmic_guard._utils`
subpackages; import from those only if you accept that they may change.
"""
from __future__ import annotations

from rmic_guard._core.contract_loader import (
    DataScope,
    ParameterConstraint,
    RMICContract,
    canonical_contract_dict_for_hash,
    compute_contract_hash,
    create_contract,
    list_example_contracts,
    load_contract,
    load_example_contract,
    seal_contract_file,
    verify_contract,
)
from rmic_guard._core.audit_ledger import AuditEntry, AuditLedger
from rmic_guard._core.embedder import set_embedding_backend
from rmic_guard._core.enforcement_engine import (
    EnforcementEngine,
    EnforcementMode,
    EnforcementOutcome,
)
from rmic_guard._core.exceptions import (
    ContractIntegrityError,
    ContractNotSealedError,
    ConfirmationNotFoundError,
    EnforcementConfigError,
    InvalidContractError,
    RMICGuardError,
    ToolExecutionNotApprovedError,
    ToolNotRegisteredError,
)
from rmic_guard._core.ids_engine import IDSEngine
from rmic_guard._core.planning import PlannedToolCall
from rmic_guard._core.tool_layer import ToolRegistry, ToolResult
from rmic_guard._core.validation import validate_contract_dict
from rmic_guard.guard import Guard, GuardResult, GuardSession

# rmic_guard._core.reasoning_layer pulls in litellm (an optional "LLM integration"
# dependency — see pyproject.toml's [anthropic]/[groq]/[llm] extras). A
# pure enforcement/contract user (`pip install rmic-guard`, no extras)
# should not be forced to have litellm installed just to import this
# package, so these three names are loaded lazily via module __getattr__
# below instead of at import time. PlannedToolCall itself is litellm-free
# (it lives in rmic_guard._core.planning) and is imported eagerly above.
_LAZY_REASONING_NAMES = {"ClaudeReasoning", "GroqReasoning", "ReasoningLayer"}


def __getattr__(name: str):  # PEP 562 lazy attribute access
    if name in _LAZY_REASONING_NAMES:
        try:
            from rmic_guard._core import reasoning_layer
        except ImportError as exc:  # pragma: no cover - exercised only without extras
            raise ImportError(
                f"rmic_guard.{name} requires the optional LLM integration dependencies. "
                'Install with: pip install "rmic-guard[llm]" (or [anthropic] / [groq]).'
            ) from exc
        return getattr(reasoning_layer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__version__ = "0.3.0"

__all__ = [
    "__version__",
    # high-level API
    "Guard",
    "GuardResult",
    "GuardSession",
    # contracts — beginner + advanced API
    "RMICContract",
    "create_contract",
    "DataScope",
    "ParameterConstraint",
    "load_contract",
    "load_example_contract",
    "list_example_contracts",
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
    "ConfirmationNotFoundError",
    # enforcement
    "EnforcementEngine",
    "EnforcementMode",
    "EnforcementOutcome",
    # drift detection
    "IDSEngine",
    "set_embedding_backend",
    # reasoning / planning
    "ReasoningLayer",
    "ClaudeReasoning",
    "GroqReasoning",
    "PlannedToolCall",
    # tools
    "ToolRegistry",
    "ToolResult",
    # audit
    "AuditLedger",
    "AuditEntry",
]
