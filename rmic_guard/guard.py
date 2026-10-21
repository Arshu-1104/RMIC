"""High-level, one-call API: ``Guard``.

    from rmic_guard import Guard

    guard = Guard("contracts/bank_bot.json")        # load + validate + seal + verify

    @guard.tool
    def transfer_funds(amount: float, to: str):
        return {"sent": amount, "to": to}

    result = guard.check("transfer_funds", amount=500, to="4321", message="pay rent")
    print(result.allowed, result.decision, result.reason, result.output)

Guard enforces the contract's hard rules by default; semantic identity-drift
detection is experimental and off by default. ``semantic="monitor"`` computes
and records the IDS without letting it change any decision; ``semantic=True``
lets it enforce.

Guard is a thin layer over the existing building blocks (RMICContract,
ToolRegistry, EnforcementEngine, AuditLedger, the reasoning backends). It
builds the PlannedToolCall, keeps the per-session IDS / tool-call history the
engine needs, executes the tool only when enforcement allows it, writes the
signed audit log, and runs the re-anchoring recovery loop for LLM plans.
"""

from __future__ import annotations

import dataclasses
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping, Union

from rmic_guard._core.audit_ledger import AuditLedger
from rmic_guard._core.contract_loader import (
    RMICContract,
    _contract_from_dict,
    _seal_dict,
    load_contract,
)
from rmic_guard._core.enforcement_engine import EnforcementEngine, EnforcementOutcome
from rmic_guard._core.exceptions import ContractNotSealedError, RMICGuardError
from rmic_guard._core.planning import PlannedToolCall
from rmic_guard._core.tool_layer import ToolRegistry

__all__ = ["Guard", "GuardResult", "GuardSession"]

ContractSource = Union[str, "os.PathLike[str]", Mapping[str, Any], RMICContract]
ToolFn = Callable[..., Any]
SemanticMode = Union[bool, Literal["monitor"]]
_ENFORCEMENT_MODES = {False: "hard_rules_only", True: "full", "monitor": "monitor"}

_ALLOWED_DECISIONS = frozenset({"PASS", "PREEMPTIVE_WARN", "CONFIRMED"})
# Bounded so a long-lived session can't grow without limit; the IDS
# trajectory and tool-frequency signals only look at a recent window anyway.
_HISTORY_LIMIT = 100
_DEFAULT_SESSION = "default"


@dataclass(frozen=True)
class GuardResult:
    """Outcome of one guarded tool call."""

    allowed: bool
    decision: str
    reason: str | None
    ids_score: float
    output: Any = None
    recovery_attempted: bool = False
    contract_hash: str = ""
    tool_name: str = ""
    executed: bool = False
    error: str | None = None
    # semantic="monitor" only: what semantic enforcement would have decided.
    ids_decision: str | None = None
    # NEEDS_CONFIRMATION: pass to guard.confirm() to execute the call (single use).
    confirmation_id: str | None = None
    # Contract deny_patterns with action "warn" that matched; the call proceeded.
    warnings: tuple[str, ...] = ()
    outcome: EnforcementOutcome | None = field(default=None, repr=False, compare=False)

    def __repr__(self) -> str:
        parts = [f"allowed={self.allowed}", f"decision={self.decision}", f"tool={self.tool_name!r}"]
        if self.reason:
            parts.append(f"reason={self.reason}")
        parts.append(f"ids_score={self.ids_score:.3f}")
        if self.output is not None:
            parts.append(f"output={self.output!r}")
        if self.ids_decision is not None:
            parts.append(f"ids_decision={self.ids_decision}")
        if self.confirmation_id is not None:
            parts.append(f"confirmation_id={self.confirmation_id!r}")
        if self.warnings:
            parts.append(f"warnings={list(self.warnings)}")
        if self.error:
            parts.append(f"error={self.error!r}")
        if self.recovery_attempted:
            parts.append("recovery_attempted=True")
        return f"GuardResult({', '.join(parts)})"

    __str__ = __repr__


def _reason_for(outcome: EnforcementOutcome) -> str | None:
    if outcome.hard_rule_violation:
        return outcome.hard_rule_violation
    if outcome.decision == "NEEDS_CONFIRMATION":
        return outcome.confirmation_reason
    if outcome.decision == "BLOCK":
        return "ids_block_threshold_exceeded"
    if outcome.decision == "NEEDS_RECOVERY":
        return "ids_warn_threshold_reached"
    if outcome.decision == "PREEMPTIVE_WARN":
        return "drift_velocity_exceeded"
    return None


def _as_categories(data: str | Iterable[str] | None) -> tuple[str, ...]:
    if not data:
        return ()
    if isinstance(data, str):
        return (data,)
    return tuple(str(d) for d in data)


def _resolve_contract(
    contract: ContractSource,
    *,
    semantic: bool,
    save_sealed: bool,
) -> RMICContract:
    if isinstance(contract, RMICContract):
        if save_sealed:
            raise ValueError("save_sealed=True needs a contract file path, not an RMICContract")
        resolved = contract
    elif isinstance(contract, Mapping):
        if save_sealed:
            raise ValueError("save_sealed=True needs a contract file path, not a dict")
        source = "Guard(<dict contract>)"
        data = dict(contract)
        if not data.get("contract_hash"):
            data = _seal_dict(data, source=source, require_embedding=semantic)
        resolved = _contract_from_dict(data, require_hash_match=True, source=source)
    elif isinstance(contract, (str, os.PathLike)):
        resolved = load_contract(
            Path(contract),
            auto_seal=True,
            write_back=save_sealed,
            require_embedding=semantic,
        )
    else:
        raise TypeError(
            f"contract must be a path, a dict, or an RMICContract, not {type(contract).__name__}"
        )

    if semantic and not resolved.anchor_embedding:
        raise ContractNotSealedError(
            f"Contract {resolved.agent_id!r} is sealed without an anchor_embedding, which semantic "
            "drift detection needs. Re-seal it with embeddings (`rmic seal <file>`) or use "
            "Guard(..., semantic=False) for hard-rules-only enforcement."
        )
    return resolved


def _make_reasoning_backend(llm: Any) -> Any:
    if hasattr(llm, "plan_tool_call"):
        return llm
    if not isinstance(llm, str) or not llm.strip():
        raise TypeError(
            "llm must be a model string such as 'groq/llama-3.3-70b-versatile' or "
            "'anthropic/claude-sonnet-4-6', or an object with a plan_tool_call(...) method"
        )
    try:
        from rmic_guard._core import reasoning_layer
    except ImportError as exc:
        raise ImportError(
            "Guard.run() needs the optional LLM integration dependencies. "
            'Install with: pip install "rmic-guard[llm]" (or [anthropic] / [groq]).'
        ) from exc
    model = llm.strip()
    provider = model.split("/", 1)[0].lower() if "/" in model else ""
    if provider == "groq":
        return reasoning_layer.GroqReasoning(model_name=model)
    if provider == "anthropic" or model.lower().startswith("claude"):
        return reasoning_layer.ClaudeReasoning(model_name=model)
    raise ValueError(
        f"Unsupported llm {llm!r}: use 'groq/<model>' or 'anthropic/<model>', "
        "or pass an object with a plan_tool_call(...) method"
    )


class _SessionState:
    __slots__ = ("recent_ids", "tool_history", "lock")

    def __init__(self) -> None:
        self.recent_ids: list[float] = []
        self.tool_history: list[str] = []
        self.lock = threading.Lock()


class GuardSession:
    """An isolated conversation view of a Guard.

    Shares the Guard's contract, tools, engine and audit log, but keeps its
    own IDS score history and tool-call history. Get one with
    ``guard.session("user-42")``; the same id always returns the same history.
    """

    def __init__(self, guard: Guard, session_id: str, state: _SessionState) -> None:
        self._guard = guard
        self.session_id = session_id
        self._state = state

    @property
    def ids_history(self) -> tuple[float, ...]:
        with self._state.lock:
            return tuple(self._state.recent_ids)

    @property
    def tool_history(self) -> tuple[str, ...]:
        with self._state.lock:
            return tuple(self._state.tool_history)

    def reset(self) -> None:
        """Forget this session's IDS and tool-call history."""
        with self._state.lock:
            self._state.recent_ids.clear()
            self._state.tool_history.clear()

    def check(
        self,
        tool_name: str,
        /,
        *,
        message: str = "",
        data: str | Iterable[str] | None = (),
        arguments: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> GuardResult:
        """Enforce one tool call and run the tool if (and only if) it is allowed.

        Tool arguments go in as keyword arguments. ``message`` (the user text
        behind the call), ``data`` (data categories the call touches) and
        ``arguments`` are reserved: pass tool parameters with those names
        through ``arguments={...}`` instead.
        """
        args = dict(arguments or {})
        args.update(kwargs)
        plan = PlannedToolCall(
            tool_name=tool_name,
            arguments=args,
            raw_text=message or "",
            data_categories_accessed=_as_categories(data),
            user_message=message or "",
        )
        return self._enforce(plan)

    def run(self, user_message: str, *, llm: Any, max_recovery: int = 1) -> GuardResult:
        """Let an LLM plan the tool call for ``user_message``, then enforce it.

        On NEEDS_RECOVERY the model re-plans with the engine's re-anchoring
        messages (up to ``max_recovery`` times). If the final plan is still not
        allowed, the result is blocked and the tool never runs.
        """
        backend = self._guard._backend_for(llm)
        contract = self._guard.contract
        plan = backend.plan_tool_call(user_message, contract=contract, condition="C")
        result = self._enforce(dataclasses.replace(plan, user_message=user_message))

        attempts = 0
        while result.decision == "NEEDS_RECOVERY" and attempts < max_recovery:
            attempts += 1
            outcome = result.outcome
            nudge = (outcome.recovery_user_message if outcome else None) or ""
            plan = backend.plan_tool_call(
                f"{user_message}\n\n{nudge}" if nudge else user_message,
                contract=contract,
                condition="C",
                extra_system=outcome.recovery_system_message if outcome else None,
            )
            result = self._enforce(dataclasses.replace(plan, user_message=user_message), recovery_attempted=True)

        if result.decision == "NEEDS_RECOVERY":
            # Recovery budget exhausted (or max_recovery=0): never let a
            # warn-zone plan through.
            reason = f"recovery_failed:{result.reason}" if attempts else result.reason
            result = GuardResult(
                allowed=False,
                decision="BLOCK",
                reason=reason,
                ids_score=result.ids_score,
                output=None,
                recovery_attempted=result.recovery_attempted,
                contract_hash=result.contract_hash,
                tool_name=result.tool_name,
                executed=False,
                error=None,
                outcome=result.outcome,
            )
        return result

    def _enforce(self, plan: PlannedToolCall, *, recovery_attempted: bool = False) -> GuardResult:
        guard = self._guard
        with self._state.lock:
            recent_ids = list(self._state.recent_ids)
            tool_history = list(self._state.tool_history)

        outcome = guard.engine.evaluate_and_maybe_execute(
            plan,
            recent_ids=recent_ids,
            tool_call_history=tool_history,
            execute_tool=guard.tools.has(plan.tool_name),
            enforcement_mode=_ENFORCEMENT_MODES[guard.semantic],
        )

        with self._state.lock:
            self._state.tool_history.append(plan.tool_name)
            del self._state.tool_history[:-_HISTORY_LIMIT]
            if guard.scores_ids:
                self._state.recent_ids.append(float(outcome.ids_score))
                del self._state.recent_ids[:-_HISTORY_LIMIT]

        tool_result = outcome.tool_result
        return GuardResult(
            allowed=outcome.decision in _ALLOWED_DECISIONS,
            decision=outcome.decision,
            reason=_reason_for(outcome),
            ids_score=float(outcome.ids_score),
            output=tool_result.data if tool_result is not None and tool_result.ok else None,
            recovery_attempted=recovery_attempted,
            contract_hash=guard.contract.contract_hash,
            tool_name=plan.tool_name,
            executed=tool_result is not None and tool_result.ok,
            error=tool_result.error if tool_result is not None and not tool_result.ok else None,
            ids_decision=outcome.ids_decision,
            confirmation_id=outcome.confirmation_id if outcome.decision == "NEEDS_CONFIRMATION" else None,
            warnings=outcome.warnings,
            outcome=outcome,
        )


class Guard:
    """Load a contract once, then enforce tool calls with a single call.

    Args:
        contract: path to a contract JSON file, a contract dict, or an
            RMICContract. Unsealed contracts are sealed in memory; sealed
            ones are hash-verified (ContractIntegrityError on tampering).
        tools: optional ToolRegistry or ``{name: callable}`` mapping.
        semantic: False (default) enforces the hard rules only (forbidden
            tools, parameter bounds, data scope): no embedding model, no
            network. True adds semantic identity-drift detection (IDS) and
            downloads the BAAI/bge-small-en-v1.5 embedding model once.
            EXPERIMENTAL: on the current scoring, attacks do not score higher
            than legitimate requests (see
            experiment/ids_calibration_investigation/post_sep22_threshold_calibration.md),
            so semantic=True blocks legitimate calls without catching attacks.
            "monitor" computes the IDS and records it in GuardResult
            (ids_score, ids_decision = what semantic=True would have decided)
            and the audit log, but never changes a decision: the hard rules
            alone decide. Use it to collect IDS data on real traffic safely.
        audit_log: path of a JSONL audit log; every decision is appended and
            Ed25519-signed.
        audit_key: path of the signing key file (default: RMIC_AUDIT_KEY, else
            ``<audit_log>.key``, created on first use).
        save_sealed: write a freshly sealed contract back to its file. Only
            meaningful when ``contract`` is a path; off by default.
    """

    def __init__(
        self,
        contract: ContractSource,
        *,
        tools: ToolRegistry | Mapping[str, ToolFn] | None = None,
        semantic: SemanticMode = False,
        audit_log: str | os.PathLike | None = None,
        audit_key: str | os.PathLike | None = None,
        save_sealed: bool = False,
    ) -> None:
        if isinstance(semantic, str) and semantic != "monitor" or not isinstance(semantic, (bool, str)):
            raise ValueError(f"semantic must be False, True or 'monitor', not {semantic!r}")
        self.semantic: SemanticMode = semantic
        self.contract = _resolve_contract(contract, semantic=self.scores_ids, save_sealed=save_sealed)

        if isinstance(tools, ToolRegistry):
            self.tools = tools
        else:
            self.tools = ToolRegistry()
            for name, fn in (tools or {}).items():
                self.tools.register(name, fn)

        if audit_log is None and audit_key is not None:
            raise ValueError("audit_key was given without audit_log")
        self.ledger = AuditLedger(audit_log, key_path=audit_key) if audit_log is not None else None
        self.engine = EnforcementEngine(contract=self.contract, tools=self.tools, ledger=self.ledger)

        self._backends: dict[str, Any] = {}
        self._sessions: dict[str, _SessionState] = {}
        self._sessions_lock = threading.Lock()
        self._default = self.session(_DEFAULT_SESSION)

    def __repr__(self) -> str:
        mode = {False: "hard-rules-only", True: "semantic", "monitor": "semantic-monitor"}[self.semantic]
        return (
            f"Guard(agent_id={self.contract.agent_id!r}, mode={mode}, "
            f"contract_hash={self.contract.contract_hash[:12]}...)"
        )

    @property
    def scores_ids(self) -> bool:
        """True when the IDS is computed (semantic=True or "monitor")."""
        return self.semantic is True or self.semantic == "monitor"

    # ---- tools ------------------------------------------------------------

    def register(self, name: str, fn: ToolFn) -> ToolFn:
        """Register ``fn`` as the implementation of tool ``name``."""
        self.tools.register(name, fn)
        return fn

    def tool(self, fn_or_name: ToolFn | str | None = None, *, name: str | None = None) -> Any:
        """Decorator form of register(): ``@guard.tool``, ``@guard.tool()`` or ``@guard.tool("name")``."""
        if callable(fn_or_name):
            return self.register(name or fn_or_name.__name__, fn_or_name)
        tool_name = fn_or_name or name

        def decorator(fn: ToolFn) -> ToolFn:
            return self.register(tool_name or fn.__name__, fn)

        return decorator

    # ---- sessions -----------------------------------------------------------

    def session(self, session_id: str) -> GuardSession:
        """Return the isolated session view for ``session_id`` (created on first use)."""
        with self._sessions_lock:
            state = self._sessions.setdefault(str(session_id), _SessionState())
        return GuardSession(self, str(session_id), state)

    def reset(self) -> None:
        """Clear the default session's IDS and tool-call history."""
        self._default.reset()

    @property
    def ids_history(self) -> tuple[float, ...]:
        return self._default.ids_history

    @property
    def tool_history(self) -> tuple[str, ...]:
        return self._default.tool_history

    # ---- enforcement --------------------------------------------------------

    def check(
        self,
        tool_name: str,
        /,
        *,
        message: str = "",
        data: str | Iterable[str] | None = (),
        arguments: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> GuardResult:
        """Enforce one tool call in the default session. See GuardSession.check."""
        return self._default.check(tool_name, message=message, data=data, arguments=arguments, **kwargs)

    def run(self, user_message: str, *, llm: Any, max_recovery: int = 1) -> GuardResult:
        """Plan with an LLM and enforce, in the default session. See GuardSession.run."""
        return self._default.run(user_message, llm=llm, max_recovery=max_recovery)

    def confirm(self, confirmation_id: str) -> GuardResult:
        """Execute a call that returned NEEDS_CONFIRMATION (e.g. an amount above
        the contract's confirm_above). Executes exactly once: the id is consumed
        and a second confirm() -- or an unknown id -- raises
        ConfirmationNotFoundError. The confirmation is written to the audit log."""
        pending_plan = self.engine.pending_plan(confirmation_id)
        execute = pending_plan is not None and self.tools.has(pending_plan.tool_name)
        outcome = self.engine.confirm(confirmation_id, execute_tool=execute)
        tool_result = outcome.tool_result
        return GuardResult(
            allowed=outcome.decision in _ALLOWED_DECISIONS,
            decision=outcome.decision,
            reason=outcome.hard_rule_violation,
            ids_score=0.0,
            output=tool_result.data if tool_result is not None and tool_result.ok else None,
            contract_hash=self.contract.contract_hash,
            tool_name=pending_plan.tool_name if pending_plan is not None else "",
            executed=tool_result is not None and tool_result.ok,
            error=tool_result.error if tool_result is not None and not tool_result.ok else None,
            confirmation_id=confirmation_id,
            outcome=outcome,
        )

    def _backend_for(self, llm: Any) -> Any:
        if not isinstance(llm, str):
            return _make_reasoning_backend(llm)
        if llm not in self._backends:
            self._backends[llm] = _make_reasoning_backend(llm)
        return self._backends[llm]

    # ---- audit --------------------------------------------------------------

    def verify_log(self) -> bool:
        """True iff every entry in the audit log carries a valid signature."""
        if self.ledger is None:
            raise RMICGuardError("verify_log() needs an audit log: Guard(..., audit_log='audit.jsonl')")
        return self.ledger.verify()
