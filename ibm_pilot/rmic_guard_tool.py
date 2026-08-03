"""
RMIC-Guard tool wrapper for IBM watsonx Orchestrate.

This module does NOT reimplement enforcement, contract loading, or audit
logging. It only adapts between two shapes:

    IBM watsonx Orchestrate agent request
        -> core.reasoning_layer.PlannedToolCall   (existing dataclass, reused)
        -> core.enforcement_engine.EnforcementEngine.evaluate_and_maybe_execute
        -> core.enforcement_engine.EnforcementOutcome
        -> IBMToolResponse                         (structured ALLOW/BLOCK)

Everything under core/ (EnforcementEngine, RMICContract, AuditLedger,
ToolRegistry) is imported and used exactly as it exists in the repository.

Run from the repository root:
    python -c "from ibm_pilot.rmic_guard_tool import RMICGuardTool; ..."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.audit_ledger import AuditLedger
from core.contract_loader import RMICContract, load_contract
from core.enforcement_engine import EnforcementEngine, EnforcementMode, EnforcementOutcome
from core.reasoning_layer import PlannedToolCall
from core.tool_layer import ToolRegistry

from ibm_pilot import config

__all__ = [
    "IBMAgentRequest",
    "IBMToolResponse",
    "RMICGuardTool",
    "build_default_tool_registry",
]


# ── Request / response shapes ────────────────────────────────────────────────


@dataclass(frozen=True)
class IBMAgentRequest:
    """
    A request as received from an IBM watsonx Orchestrate agent.

    The Orchestrate agent has already decided which business tool it wants
    to call and with which arguments (this is how Orchestrate custom-tool
    invocation works) — RMIC-Guard's job is to check that call against the
    sealed identity contract before it is allowed to run.

    Attributes:
        user_message: The original end-user text. Kept verbatim because the
            IDS engine scores semantic drift against this text, not against
            the tool_name/arguments alone (see core.enforcement_engine._ids_on_plan).
        tool_name: The business tool the Orchestrate agent has selected.
        arguments: Arguments the Orchestrate agent wants to pass to that tool.
        data_categories_accessed: Data categories the Orchestrate agent
            reports this call as touching (checked against the contract's
            data_scope.prohibited list). Optional — defaults to none.
        drift_type: Optional label for the audit entry (e.g. "permission_drift"),
            purely descriptive, passed straight through to AuditEntry.drift_type.
    """

    user_message: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    data_categories_accessed: tuple[str, ...] = ()
    drift_type: str | None = None


@dataclass(frozen=True)
class IBMToolResponse:
    """
    Structured response handed back to the IBM watsonx Orchestrate agent.

    `decision` is deliberately collapsed to the two outcomes Orchestrate
    needs to branch on ("ALLOW" / "BLOCK"). `raw_decision` preserves the
    full-fidelity EnforcementOutcome.decision ("PASS", "WARN", "BLOCK",
    "NEEDS_RECOVERY", "PREEMPTIVE_WARN") for logging/debugging.
    """

    decision: str  # "ALLOW" | "BLOCK"
    raw_decision: str
    ids_score: float
    drift_velocity: float
    hard_rule_violation: str | None
    reason: str
    tool_result_ok: bool | None
    tool_result_data: Any
    tool_result_error: str | None
    contract_hash: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form for returning over the Orchestrate tool
        response channel."""
        return {
            "decision": self.decision,
            "raw_decision": self.raw_decision,
            "ids_score": self.ids_score,
            "drift_velocity": self.drift_velocity,
            "hard_rule_violation": self.hard_rule_violation,
            "reason": self.reason,
            "tool_result": {
                "ok": self.tool_result_ok,
                "data": self.tool_result_data,
                "error": self.tool_result_error,
            },
            "contract_hash": self.contract_hash,
        }


# ── Adapters between IBM shapes and existing RMIC dataclasses ───────────────


def _to_planned_tool_call(request: IBMAgentRequest) -> PlannedToolCall:
    """Adapt an IBMAgentRequest into the existing PlannedToolCall dataclass.

    No new "plan" dataclass is introduced — this reuses
    core.reasoning_layer.PlannedToolCall exactly as EnforcementEngine expects it.
    """

    tool_aliases = {
    "ElectronicFundsTransfer": "transfer_funds",
    "AccountBalanceInquiry": "check_balance",
    "GetAccountBalance": "check_balance",
    "TransactionHistoryLookup": "get_transaction_history",
    "TransferConfirmation": "send_transfer_confirmation",
}

    normalized_tool = tool_aliases.get(
        request.tool_name,
        request.tool_name
    )

    return PlannedToolCall(
        tool_name=normalized_tool,
        arguments=dict(request.arguments),
        raw_text=request.user_message,
        data_categories_accessed=tuple(request.data_categories_accessed),
    )


def _outcome_to_ibm_response(
    outcome: EnforcementOutcome,
    contract: RMICContract,
) -> IBMToolResponse:
    """Adapt an EnforcementOutcome into the structured IBM response.

    Decision collapsing follows the same rule demo.py's _outcome_label()
    uses: PASS and PREEMPTIVE_WARN are treated as an allowed execution;
    everything else (BLOCK, WARN, NEEDS_RECOVERY) is treated as not allowed,
    since EnforcementEngine only executes the tool for PASS/PREEMPTIVE_WARN.
    """
    allowed = outcome.decision in ("PASS", "PREEMPTIVE_WARN", "WARN", "NEEDS_RECOVERY")
    decision = "ALLOW" if allowed else "BLOCK"

    if outcome.hard_rule_violation:
        reason = f"hard_rule_violation:{outcome.hard_rule_violation}"
    elif outcome.decision == "BLOCK":
        reason = "ids_block_threshold_exceeded"
    elif outcome.decision in ("WARN", "NEEDS_RECOVERY"):
        reason = "ids_warn_threshold_reached"
    elif outcome.decision == "PREEMPTIVE_WARN":
        reason = "passed_with_elevated_drift_velocity"
    else:
        reason = "passed_all_checks"

    tr = outcome.tool_result
    return IBMToolResponse(
        decision=decision,
        raw_decision=outcome.decision,
        ids_score=outcome.ids_score,
        drift_velocity=outcome.drift_velocity,
        hard_rule_violation=outcome.hard_rule_violation,
        reason=reason,
        tool_result_ok=None if tr is None else tr.ok,
        tool_result_data=None if tr is None else tr.data,
        tool_result_error=None if tr is None else tr.error,
        contract_hash=contract.contract_hash,
    )


# ── Business-tool stubs (downstream of ALLOW; not enforcement logic) ────────


def _stub_business_tool(**kwargs: object) -> dict[str, object]:
    """Placeholder business-tool executor — no real banking side effects.

    This sits *after* the ALLOW decision in the execution flow (RMIC Guard
    Tool -> Enforcement Engine -> Decision -> ALLOW -> Execute Business Tool).
    It is intentionally trivial: RMIC-Guard's enforcement logic is what's
    being piloted here, not a banking backend. Replace with real tool
    callables via RMICGuardTool(tools=...) for a production integration.
    """
    return {"ok": True, "received": kwargs}


def build_default_tool_registry() -> ToolRegistry:
    """Build a ToolRegistry pre-populated with stub business tools for every
    allowed_action in the financial_agent contract (config.DEFAULT_CONTRACT_PATH).

    Uses core.tool_layer.ToolRegistry exactly as defined in the repository —
    no subclassing, no new registry type.
    """
    registry = ToolRegistry()
    for name in (
        "transfer_funds",
        "check_balance",
        "get_transaction_history",
        "send_transfer_confirmation",
    ):
        registry.register(name, _stub_business_tool)
    return registry


# ── The pilot tool itself ────────────────────────────────────────────────────


class RMICGuardTool:
    """
    IBM watsonx Orchestrate custom tool wrapper around the existing
    RMIC-Guard enforcement pipeline.

    This class holds no enforcement logic of its own. Construction loads an
    existing sealed contract with core.contract_loader.load_contract, opens
    the existing core.audit_ledger.AuditLedger at the configured path, and
    builds one core.enforcement_engine.EnforcementEngine — the same three
    calls demo.py and examples/quickstart.py already make. handle_request()
    only adapts shapes; evaluate_and_maybe_execute() does the actual work.
    """

    def __init__(
        self,
        *,
        contract_path: str | None = None,
        audit_log_path: str | None = None,
        tools: ToolRegistry | None = None,
        enforcement_mode: EnforcementMode = config.ENFORCEMENT_MODE,
        verify_contract_hash: bool = config.VERIFY_CONTRACT_HASH,
    ) -> None:
        """
        Args:
            contract_path: Path to a sealed RMIC contract JSON file. Defaults
                to config.DEFAULT_CONTRACT_PATH (contracts/financial_agent.json).
            audit_log_path: Path to the audit ledger JSONL file. Defaults to
                config.AUDIT_LOG_PATH (results/ibm_pilot_audit.jsonl).
            tools: A pre-populated ToolRegistry for the business tools this
                agent may call. Defaults to build_default_tool_registry().
            enforcement_mode: "full" | "hard_rules_only" | "ids_only",
                forwarded unchanged to EnforcementEngine.evaluate_and_maybe_execute.
            verify_contract_hash: Whether load_contract should verify the
                stored contract_hash. Defaults to config.VERIFY_CONTRACT_HASH.
        """
        path = contract_path or str(config.DEFAULT_CONTRACT_PATH)
        self.contract: RMICContract = load_contract(path, verify_hash=verify_contract_hash)

        ledger_path = audit_log_path or str(config.AUDIT_LOG_PATH)
        self.ledger = AuditLedger(ledger_path)

        self.tools: ToolRegistry = tools if tools is not None else build_default_tool_registry()
        self.engine = EnforcementEngine(self.contract, self.tools, ledger=self.ledger)
        self.enforcement_mode: EnforcementMode = enforcement_mode

        # Per-tool-instance trajectory state, mirroring the recent_ids /
        # tool_call_history lists demo.py keeps across a query loop. In a
        # real Orchestrate deployment this should be keyed per conversation
        # session rather than per-process; see README "Limitations".
        self._recent_ids: list[float] = []
        self._tool_call_history: list[str] = []

        print(
            f"[RMICGuardTool] initialised agent_id={self.contract.agent_id!r} "
            f"contract_hash={self.contract.contract_hash[:12]}... "
            f"mode={self.enforcement_mode!r}"
        )

    def handle_request(
        self,
        request: IBMAgentRequest,
        *,
        execute_tool: bool = True,
    ) -> IBMToolResponse:
        """
        Entry point called by the IBM watsonx Orchestrate agent (directly,
        or via the wrapper in ibm_pilot/agent_example.py).

        Adapts `request` into the existing PlannedToolCall, calls the
        existing EnforcementEngine.evaluate_and_maybe_execute exactly as
        demo.py does, updates this instance's trajectory state, and adapts
        the resulting EnforcementOutcome into a structured IBMToolResponse.

        Args:
            request: The IBM agent's requested tool call.
            execute_tool: Whether to actually invoke the underlying business
                tool on ALLOW. Set False for a dry-run / preview call.

        Returns:
            IBMToolResponse with decision "ALLOW" or "BLOCK".
        """
        plan = _to_planned_tool_call(request)

        print(
            f"[RMICGuardTool] request tool_name={plan.tool_name!r} "
            f"arguments={plan.arguments}"
        )

        outcome = self.engine.evaluate_and_maybe_execute(
            plan,
            recent_ids=list(self._recent_ids),
            tool_call_history=list(self._tool_call_history),
            drift_type=request.drift_type,
            execute_tool=execute_tool,
            enforcement_mode=self.enforcement_mode,
        )

        self._recent_ids.append(outcome.ids_score)
        self._tool_call_history.append(plan.tool_name)

        response = _outcome_to_ibm_response(outcome, self.contract)

        print(
            f"[RMICGuardTool] decision={response.decision} "
            f"raw_decision={response.raw_decision} ids_score={response.ids_score:.4f} "
            f"reason={response.reason}"
        )

        return response

    def reset_session(self) -> None:
        """Clear per-session trajectory state (recent_ids, tool_call_history).

        Call this between unrelated Orchestrate conversations so drift
        velocity/curvature from one user's session doesn't leak into the next.
        """
        self._recent_ids.clear()
        self._tool_call_history.clear()