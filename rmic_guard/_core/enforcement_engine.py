"""
Dual enforcement between reasoning output and tool execution.

Pass 1: hard rules (forbidden tools, argument rules, parameter bounds, data
        scope, contract deny patterns).
Pass 2: IDS composite; block only when IDS >= block threshold.
Before a tool executes: contract confirm_above limits turn the call into
NEEDS_CONFIRMATION; confirm(confirmation_id) executes it exactly once.
Pending confirmations expire after a TTL (the contract's value is a ceiling),
are capped in number (oldest evicted first) and can be listed or cancelled.
"""

from __future__ import annotations

import secrets
import threading
import time
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, NamedTuple

from rmic_guard._core.audit_ledger import AuditEntry, AuditLedger, hash_text
from rmic_guard._core.contract_loader import RMICContract
from rmic_guard._core.exceptions import ConfirmationNotFoundError, EnforcementConfigError, RMICGuardWarning
from rmic_guard._core.hard_rules import check_argument_rules, confirmation_reason, deny_pattern_matches
from rmic_guard._core.ids_engine import IDSEngine
from rmic_guard._core.recovery_engine import reanchoring_system_message, reanchoring_user_nudge
from rmic_guard._core.planning import PlannedToolCall
from rmic_guard._core.tool_layer import ToolRegistry, ToolResult
from rmic_guard._utils.config import load_user_config

__all__ = [
    "DEFAULT_CONFIRMATION_TTL_SECONDS",
    "DEFAULT_MAX_PENDING_CONFIRMATIONS",
    "EnforcementEngine",
    "EnforcementMode",
    "EnforcementOutcome",
    "PendingConfirmation",
]

DEFAULT_CONFIRMATION_TTL_SECONDS = 600.0
DEFAULT_MAX_PENDING_CONFIRMATIONS = 100
# Expired/evicted/cancelled ids remembered so confirm() can say why it failed.
_MIN_CONFIRMATION_TOMBSTONES = 1_000

Decision = Literal[
    "PASS", "BLOCK", "WARN", "NEEDS_RECOVERY", "PREEMPTIVE_WARN", "NEEDS_CONFIRMATION", "CONFIRMED"
]

EnforcementMode = Literal["full", "hard_rules_only", "ids_only", "monitor"]


@dataclass(frozen=True)
class EnforcementOutcome:
    decision: Decision
    ids_score: float
    drift_velocity: float
    ids_components: dict[str, float] | None
    hard_rule_violation: str | None
    recovery_system_message: str | None
    recovery_user_message: str | None
    tool_result: ToolResult | None
    # "monitor" mode only: what "full" mode would have decided from the IDS
    # (PASS / PREEMPTIVE_WARN / NEEDS_RECOVERY / BLOCK). None in other modes.
    ids_decision: str | None = None
    # NEEDS_CONFIRMATION / CONFIRMED: the single-use id for confirm(), and why
    # confirmation is needed ("confirm_above:<param>").
    confirmation_id: str | None = None
    confirmation_reason: str | None = None
    # Contract deny_patterns with action "warn" that matched (the call proceeds),
    # and deny_pattern_scan_truncated:<N> when only part of the message was scanned.
    warnings: tuple[str, ...] = ()


def _numeric_for_type(val: Any, value_type: str) -> float:
    if value_type == "int":
        return float(int(val))
    return float(val)


def _check_parameter_constraints(
    contract: RMICContract,
    arguments: dict[str, Any],
) -> str | None:
    by_name = contract.constraints_by_name()
    for name, spec in by_name.items():
        if name not in arguments:
            continue
        try:
            v = _numeric_for_type(arguments[name], spec.value_type)
        except (TypeError, ValueError):
            return f"parameter_constraint:{name}:not_numeric"
        if spec.max is not None and v > float(spec.max):
            return f"parameter_constraint:{name}:above_max"
        if spec.min is not None and v < float(spec.min):
            return f"parameter_constraint:{name}:below_min"
    return None


def _check_data_scope(contract: RMICContract, plan: PlannedToolCall) -> str | None:
    prohibited = set(contract.data_scope.prohibited)
    for cat in plan.data_categories_accessed:
        if cat in prohibited:
            return f"data_scope:prohibited:{cat}"
    return None


def _normalize_tool_name(name: str) -> str:
    """Case/whitespace-insensitive form used only for matching, never for execution."""
    return (name or "").strip().lower().replace(" ", "_").replace("-", "_")


def _check_hard_rules(contract: RMICContract, plan: PlannedToolCall) -> str | None:
    planned = _normalize_tool_name(plan.tool_name)
    forbidden_norm = {_normalize_tool_name(a) for a in contract.forbidden_actions}
    allowed_norm = {_normalize_tool_name(a) for a in contract.allowed_actions}

    if planned in forbidden_norm:
        return "forbidden_tool"
    if allowed_norm and planned not in allowed_norm:
        return "tool_not_allowed"
    ar = check_argument_rules(contract.argument_rules, plan.tool_name, plan.arguments)
    if ar:
        return ar
    pr = _check_parameter_constraints(contract, plan.arguments)
    if pr:
        return pr
    ds = _check_data_scope(contract, plan)
    if ds:
        return ds
    blocked, _ = deny_pattern_matches(contract.deny_patterns, _deny_text(plan))
    return blocked


def _deny_text(plan: PlannedToolCall) -> str:
    """Deny patterns look at the user's words only, never the model's output."""
    return plan.user_message if plan.user_message is not None else plan.raw_text


def _join_reasons(*reasons: str | None) -> str | None:
    parts = [r for r in reasons if r]
    return ";".join(parts) if parts else None


def _ids_on_plan(
    contract: RMICContract,
    plan: PlannedToolCall,
    recent_ids: list[float],
    tool_call_history: list[str] | None = None,
) -> tuple[float, dict[str, float]]:
    """
    Compute IDS score and component breakdown for a planned tool call.

    Args:
        contract: The sealed RMIC contract.
        plan: Planned tool call with semantic context.
        recent_ids: History of prior IDS scores (for trajectory curvature).
        tool_call_history: Sequence of tool names called in this session.

    Returns:
        Tuple of (base_ids_score, components_dict). The components dictionary
        contains all independent drift metrics used for dashboard visualization.

    Raises:
        ValueError: If contract.anchor_embedding is empty (contract not sealed).
    """
    if not contract.anchor_embedding:
        raise ValueError("contract missing anchor_embedding — run seal_contract_file first")
    text_for_ids = f"{plan.tool_name} {plan.arguments} {plan.raw_text}"
    allowed_topics = list(contract.semantic_anchors)
    # TODO: forbidden_topics is intentionally empty. Until 22 Sep 2026 (PR #5)
    # it was filled with contract.data_scope.prohibited + forbidden_actions.
    # This matters for the paper's numbers: semantic_grounding is
    # 1 - (sim(allowed) - sim(forbidden)), so with no forbidden topics it loses
    # the +sim(forbidden) term and Base IDS drops for practically every input
    # (bge similarities are positive); the mahalanobis/KL/JS/wasserstein/
    # hellinger signals also change, since they embed allowed + forbidden
    # topics. IDS results produced before 22 Sep are therefore not
    # reproducible with this code: re-run the experiment, or state which
    # version produced the figures, before citing them. Re-populating this
    # list is a scoring change that needs re-calibration.
    forbidden_topics: list[str] = []
    components = IDSEngine().score(
        text_for_ids,
        anchor_embedding=contract.anchor_embedding,
        allowed_topics=allowed_topics,
        forbidden_topics=forbidden_topics,
        recent_ids=recent_ids,
        tool_call_history=list(tool_call_history or []) + [plan.tool_name],
        allowed_actions=tuple(contract.allowed_actions),
    )
    return components["base_ids"], components


def _velocity(recent_ids: list[float], new_ids: float) -> float:
    if not recent_ids:
        return 0.0
    return abs(new_ids - recent_ids[-1])


@dataclass(frozen=True)
class PendingConfirmation:
    """A NEEDS_CONFIRMATION call waiting for confirm() or cancel()."""

    confirmation_id: str
    tool_name: str
    arguments: dict[str, Any]
    reason: str | None  # e.g. "confirm_above:amount"
    created_at: datetime  # UTC
    expires_at: datetime  # UTC; confirm() fails from then on


class _Pending(NamedTuple):
    plan: PlannedToolCall
    issued: float  # engine clock (monotonic), for expiry
    created_at: datetime  # wall clock, for display
    reason: str | None


def _effective_ttl(contract: RMICContract, requested: float | None) -> float:
    """The contract's confirmation_ttl_seconds is a ceiling: an engine/Guard
    argument can shorten it but never lengthen it. Without a contract value
    the argument (or the default) applies."""
    if requested is not None and (
        isinstance(requested, bool) or not isinstance(requested, (int, float)) or not 0 < requested < float("inf")
    ):
        raise EnforcementConfigError(f"confirmation_ttl_seconds must be a positive number, not {requested!r}")
    ceiling = contract.confirmation_ttl_seconds
    if ceiling is None:
        return float(DEFAULT_CONFIRMATION_TTL_SECONDS if requested is None else requested)
    if requested is None:
        return float(ceiling)
    if requested > ceiling:
        warnings.warn(
            f"confirmation_ttl_seconds={requested:g} is ignored: contract {contract.agent_id!r} sets "
            f"confirmation_ttl_seconds={ceiling:g}, which can be shortened but not lengthened.",
            RMICGuardWarning,
            stacklevel=4,
        )
        return float(ceiling)
    return float(requested)


class EnforcementEngine:
    def __init__(
        self,
        contract: RMICContract,
        tools: ToolRegistry,
        ledger: AuditLedger | None = None,
        log_async: Callable[[AuditEntry], None] | None = None,
        *,
        confirmation_ttl_seconds: float | None = None,
        max_pending_confirmations: int = DEFAULT_MAX_PENDING_CONFIRMATIONS,
    ) -> None:
        self.contract = contract
        self.tools = tools
        self.ledger = ledger
        self.log_async = log_async
        self._tool_approval_token = tools.issue_approval_token()
        self.confirmation_ttl_seconds = _effective_ttl(contract, confirmation_ttl_seconds)
        max_pending = max_pending_confirmations
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 1:
            raise EnforcementConfigError(
                f"max_pending_confirmations must be a positive integer, not {max_pending_confirmations!r}"
            )
        self.max_pending_confirmations = max_pending_confirmations
        self._clock: Callable[[], float] = time.monotonic
        # confirmation_id -> parked call awaiting confirm(), oldest first; each
        # id is removed on use, cancel, expiry or eviction.
        self._pending_confirmations: OrderedDict[str, _Pending] = OrderedDict()
        # Expired / evicted / cancelled ids -> (why, input hash), so confirm()
        # can explain (and audit) the failure. Bounded: the oldest are forgotten.
        self._dead_confirmations: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._pending_lock = threading.Lock()
        # The contract's own thresholds are authoritative. A config file only
        # overrides them when one was named explicitly (path / RMIC_CONFIG) and
        # actually sets the key -- built-in defaults never mask contract values.
        tcfg = load_user_config().get("thresholds") or {}
        self.ids_warn_threshold = float(tcfg.get("warn_threshold", contract.ids_warn_threshold))
        self.ids_block_threshold = float(tcfg.get("block_threshold", contract.ids_block_threshold))
        self.drift_velocity_threshold = float(
            tcfg.get("velocity_threshold", contract.drift_velocity_threshold)
        )

    def _log(self, entry: AuditEntry, *, sync: bool) -> None:
        if self.ledger is None:
            return
        if sync:
            self.ledger.append(entry)
        elif self.log_async:
            self.log_async(entry)
        else:
            self.ledger.append(entry)

    def _pre_execution_gate(
        self, plan: PlannedToolCall, enforcement_mode: EnforcementMode
    ) -> tuple[str | None, str | None, tuple[str, ...]]:
        """For a plan that passed every blocking check: (confirmation reason,
        confirmation id, deny-pattern warnings). A confirmation reason means the
        tool must not run now; the plan is parked under the returned id."""
        if enforcement_mode == "ids_only":  # hard rules (and these extensions) are skipped
            return None, None, ()
        _, warnings = deny_pattern_matches(self.contract.deny_patterns, _deny_text(plan))
        reason = confirmation_reason(self.contract.parameter_constraints, plan.arguments)
        if reason is None:
            return None, None, warnings
        confirmation_id = secrets.token_urlsafe(16)
        with self._pending_lock:
            self._expire_locked()
            while len(self._pending_confirmations) >= self.max_pending_confirmations:
                old_id, old = self._pending_confirmations.popitem(last=False)
                self._bury_locked(old_id, "evicted", old.plan)
            self._pending_confirmations[confirmation_id] = _Pending(
                plan, self._clock(), datetime.now(timezone.utc), reason
            )
        return reason, confirmation_id, warnings

    def _bury_locked(self, confirmation_id: str, why: str, plan: PlannedToolCall) -> None:
        self._dead_confirmations[confirmation_id] = (why, hash_text(plan.raw_text))
        limit = max(_MIN_CONFIRMATION_TOMBSTONES, self.max_pending_confirmations)
        while len(self._dead_confirmations) > limit:
            self._dead_confirmations.popitem(last=False)

    def _expire_locked(self) -> None:
        # Insertion order is issue order and the TTL is fixed, so expired
        # entries are always a prefix.
        cutoff = self._clock() - self.confirmation_ttl_seconds
        while self._pending_confirmations:
            cid, pending = next(iter(self._pending_confirmations.items()))
            if pending.issued > cutoff:
                break
            del self._pending_confirmations[cid]
            self._bury_locked(cid, "expired", pending.plan)

    @property
    def pending_confirmations(self) -> int:
        """Number of NEEDS_CONFIRMATION calls not yet confirmed, cancelled, expired or evicted."""
        with self._pending_lock:
            self._expire_locked()
            return len(self._pending_confirmations)

    def list_pending_confirmations(self) -> tuple[PendingConfirmation, ...]:
        """The calls awaiting confirm(), oldest first (expired ones are dropped first)."""
        with self._pending_lock:
            self._expire_locked()
            return tuple(self._describe(cid, p) for cid, p in self._pending_confirmations.items())

    def _describe(self, confirmation_id: str, pending: _Pending) -> PendingConfirmation:
        return PendingConfirmation(
            confirmation_id=confirmation_id,
            tool_name=pending.plan.tool_name,
            arguments=dict(pending.plan.arguments),
            reason=pending.reason,
            created_at=pending.created_at,
            expires_at=pending.created_at + timedelta(seconds=self.confirmation_ttl_seconds),
        )

    def pending_plan(self, confirmation_id: str) -> PlannedToolCall | None:
        """The call waiting under confirmation_id (None if unknown, used, expired or evicted)."""
        with self._pending_lock:
            self._expire_locked()
            entry = self._pending_confirmations.get(confirmation_id)
        return None if entry is None else entry.plan

    def _audit_confirmation_end(self, confirmation_id: str, why: str, input_hash: str) -> None:
        c = self.contract
        self._log(
            AuditEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent_id=c.agent_id,
                input_hash=input_hash,
                ids_score=0.0,
                drift_type=None,
                drift_velocity=None,
                decision="BLOCK",
                failure_reason=f"confirmation_{why}",
                contract_hash=c.contract_hash,
                recovery_attempted=False,
                confirmation_id=confirmation_id,
            ),
            sync=True,
        )

    def _confirmation_failed(self, confirmation_id: str, why: str, input_hash: str) -> ConfirmationNotFoundError:
        """Audit a confirm() of an expired or evicted id (a cancellation was
        audited when it happened); return the error to raise."""
        if why != "cancelled":
            self._audit_confirmation_end(confirmation_id, why, input_hash)
        if why == "expired":
            detail = (
                f"it expired: confirmations are valid for {self.confirmation_ttl_seconds:g} s "
                "(confirmation_ttl_seconds)"
            )
        elif why == "evicted":
            detail = (
                f"it was evicted: at most {self.max_pending_confirmations} confirmations can be "
                "pending (max_pending_confirmations) and it was the oldest"
            )
        else:
            detail = "it was cancelled"
        return ConfirmationNotFoundError(
            f"Confirmation {confirmation_id!r} failed, {detail}. The call was not executed; "
            "submit it again to get a new confirmation id.",
            reason=why,
        )

    def cancel(self, confirmation_id: str) -> PendingConfirmation:
        """Withdraw a pending confirmation without executing it. The cancellation
        is audited (BLOCK, failure_reason confirmation_cancelled, same
        confirmation_id); a later confirm() raises ConfirmationNotFoundError
        with reason "cancelled". An id that is not pending raises
        ConfirmationNotFoundError (reason "expired", "evicted", "cancelled"
        or "unknown")."""
        with self._pending_lock:
            self._expire_locked()
            entry = self._pending_confirmations.pop(confirmation_id, None)
            if entry is not None:
                self._bury_locked(confirmation_id, "cancelled", entry.plan)
            dead = self._dead_confirmations.get(confirmation_id) if entry is None else None
        if entry is None:
            why = dead[0] if dead is not None else "unknown"
            raise ConfirmationNotFoundError(
                f"Cannot cancel {confirmation_id!r}: it is not pending ({why}).", reason=why
            )
        self._audit_confirmation_end(confirmation_id, "cancelled", hash_text(entry.plan.raw_text))
        return self._describe(confirmation_id, entry)

    def confirm(self, confirmation_id: str, *, execute_tool: bool = True) -> EnforcementOutcome:
        """Execute a call that returned NEEDS_CONFIRMATION. Single use: the id
        is consumed before anything runs, so a second confirm() raises
        ConfirmationNotFoundError. Hard rules are re-checked; the confirmation
        is written to the audit log (decision CONFIRMED, same confirmation_id
        as the NEEDS_CONFIRMATION entry).

        An id older than confirmation_ttl_seconds, or evicted because more than
        max_pending_confirmations were pending, raises ConfirmationNotFoundError
        with reason "expired" / "evicted"; that failure is audited as a BLOCK
        with failure_reason confirmation_expired / confirmation_evicted. A
        cancelled id raises with reason "cancelled" (audited by cancel())."""
        with self._pending_lock:
            self._expire_locked()
            entry = self._pending_confirmations.pop(confirmation_id, None)
            dead = self._dead_confirmations.pop(confirmation_id, None) if entry is None else None
        if dead is not None:
            raise self._confirmation_failed(confirmation_id, *dead)
        if entry is None:
            raise ConfirmationNotFoundError(
                f"No pending confirmation {confirmation_id!r}: it was never issued by this engine "
                "or has already been used.",
                reason="unknown",
            )
        plan = entry.plan
        c = self.contract
        hard = _check_hard_rules(c, plan)  # contracts are immutable; defensive only
        decision: Decision = "BLOCK" if hard else "CONFIRMED"
        self._log(
            AuditEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                agent_id=c.agent_id,
                input_hash=hash_text(plan.raw_text),
                ids_score=0.0,
                drift_type=None,
                drift_velocity=None,
                decision=decision,
                failure_reason=hard,
                contract_hash=c.contract_hash,
                recovery_attempted=False,
                confirmation_id=confirmation_id,
            ),
            sync=True,
        )
        tool_result: ToolResult | None = None
        if not hard and execute_tool:
            tool_result = self.tools.execute(plan.tool_name, approval_token=self._tool_approval_token, **plan.arguments)
        return EnforcementOutcome(
            decision=decision,
            ids_score=0.0,
            drift_velocity=0.0,
            ids_components=None,
            hard_rule_violation=hard,
            recovery_system_message=None,
            recovery_user_message=None,
            tool_result=tool_result,
            confirmation_id=confirmation_id,
        )

    def evaluate_and_maybe_execute(
        self,
        plan: PlannedToolCall,
        *,
        recent_ids: list[float],
        tool_call_history: list[str] | None = None,
        drift_type: str | None = None,
        execute_tool: bool = True,
        enforcement_mode: EnforcementMode = "full",
    ) -> EnforcementOutcome:
        """
        Run dual enforcement. Executes the tool only when decision is PASS and execute_tool is True.
        Below warn threshold: append audit with sync=False when log_async is set (caller may flush).

        enforcement_mode:
          full — hard rules then IDS (default).
          hard_rules_only — Pass 1 only; if hard rules pass, PASS with ids_score=0 (no IDS).
          ids_only — Pass 2 only; skip hard rules, block only on IDS thresholds.
          monitor — hard rules decide; the IDS is computed and recorded (outcome,
            audit log) but never changes the decision. outcome.ids_decision holds
            what "full" would have decided.

        In every mode except ids_only, a call that would execute but has an
        argument above a contract confirm_above limit returns NEEDS_CONFIRMATION
        instead (tool not run; see confirm()), and deny_patterns with action
        "warn" are reported in outcome.warnings.
        """
        c = self.contract
        if enforcement_mode == "ids_only":
            hard = None
        else:
            hard = _check_hard_rules(c, plan)
        if hard:
            # A deny-pattern block also reports warn matches before it and
            # scan truncation; other hard rules fire before deny patterns run.
            block_notes: tuple[str, ...] = ()
            if hard.startswith("deny_pattern:"):
                _, block_notes = deny_pattern_matches(c.deny_patterns, _deny_text(plan))
            # Compute IDS even on hard-rule block so the dashboard always has
            # real embedding scores for every Condition C row.
            ids_score_measured = 0.0
            ids_components_measured: dict[str, float] | None = None
            if c.anchor_embedding and enforcement_mode not in ("hard_rules_only",):
                try:
                    ids_score_measured, ids_components_measured = _ids_on_plan(
                        c,
                        plan,
                        recent_ids,
                        tool_call_history=tool_call_history,
                    )
                except Exception:
                    ids_score_measured = 0.0
                    ids_components_measured = None
            self._log(
                AuditEntry(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    agent_id=c.agent_id,
                    input_hash=hash_text(plan.raw_text),
                    ids_score=ids_score_measured,
                    role_distance=(
                        None
                        if not ids_components_measured
                        else ids_components_measured.get("role_distance")
                    ),
                    semantic_grounding=(
                        None
                        if not ids_components_measured
                        else ids_components_measured.get("semantic_grounding")
                    ),
                    trajectory_curvature=(
                        None
                        if not ids_components_measured
                        else ids_components_measured.get("trajectory_curvature")
                    ),
                    drift_type=drift_type,
                    drift_velocity=None,
                    decision="BLOCK",
                    failure_reason=_join_reasons(hard, *block_notes),
                    false_positive=False,
                    false_negative=False,
                    contract_hash=c.contract_hash,
                    recovery_attempted=False,
                ),
                sync=True,
            )
            return EnforcementOutcome(
                decision="BLOCK",
                ids_score=ids_score_measured,
                drift_velocity=0.0,
                ids_components=ids_components_measured,
                hard_rule_violation=hard,
                recovery_system_message=None,
                recovery_user_message=None,
                tool_result=None,
                warnings=block_notes,
            )

        gate_reason, confirmation_id, warnings = self._pre_execution_gate(plan, enforcement_mode)

        if enforcement_mode == "hard_rules_only":
            pass_sync = self.log_async is None or gate_reason is not None
            hr_decision: Decision = "NEEDS_CONFIRMATION" if gate_reason else "PASS"
            self._log(
                AuditEntry(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    agent_id=c.agent_id,
                    input_hash=hash_text(plan.raw_text),
                    ids_score=0.0,
                    drift_type=drift_type,
                    drift_velocity=None,
                    decision=hr_decision,
                    failure_reason=_join_reasons(gate_reason, *warnings),
                    false_positive=False,
                    false_negative=False,
                    contract_hash=c.contract_hash,
                    recovery_attempted=False,
                    confirmation_id=confirmation_id,
                ),
                sync=pass_sync,
            )
            tool_result: ToolResult | None = None
            if execute_tool and gate_reason is None:
                tool_result = self.tools.execute(
                    plan.tool_name,
                    approval_token=self._tool_approval_token,
                    **plan.arguments,
                )
            return EnforcementOutcome(
                decision=hr_decision,
                ids_score=0.0,
                drift_velocity=0.0,
                ids_components=None,
                hard_rule_violation=None,
                recovery_system_message=None,
                recovery_user_message=None,
                tool_result=tool_result,
                confirmation_id=confirmation_id,
                confirmation_reason=gate_reason,
                warnings=warnings,
            )

        ids_score, ids_components = _ids_on_plan(
            c,
            plan,
            recent_ids,
            tool_call_history=tool_call_history,
        )
        vel = _velocity(recent_ids, ids_score)

        def audit(
            decision: str,
            recovery_attempted: bool,
            *,
            sync_log: bool,
            failure_reason: str | None = None,
            confirmation_id: str | None = None,
        ) -> None:
            self._log(
                AuditEntry(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    agent_id=c.agent_id,
                    input_hash=hash_text(plan.raw_text),
                    ids_score=ids_score,
                    role_distance=ids_components.get("role_distance"),
                    semantic_grounding=ids_components.get("semantic_grounding"),
                    trajectory_curvature=ids_components.get("trajectory_curvature"),
                    drift_type=drift_type,
                    drift_velocity=vel,
                    decision=decision,
                    failure_reason=failure_reason or (
                        "ids_block_threshold_exceeded"
                        if decision == "BLOCK"
                        else ("ids_warn_threshold_reached" if decision == "WARN" else None)
                    ),
                    false_positive=False,
                    false_negative=False,
                    contract_hash=c.contract_hash,
                    recovery_attempted=recovery_attempted,
                    confirmation_id=confirmation_id,
                ),
                sync=sync_log,
            )

        if enforcement_mode == "monitor":
            # Hard rules already passed. The IDS is measured and recorded but
            # never changes the decision; ids_decision says what "full" mode
            # would have done (also noted as failure_reason in the audit log).
            if ids_score >= self.ids_block_threshold:
                shadow = "BLOCK"
            elif ids_score >= self.ids_warn_threshold:
                shadow = "NEEDS_RECOVERY"
            elif vel > self.drift_velocity_threshold:
                shadow = "PREEMPTIVE_WARN"
            else:
                shadow = "PASS"
            monitor_decision: Decision = "NEEDS_CONFIRMATION" if gate_reason else "PASS"
            audit(
                monitor_decision,
                False,
                sync_log=self.log_async is None or shadow != "PASS" or gate_reason is not None,
                failure_reason=_join_reasons(
                    gate_reason, None if shadow == "PASS" else f"monitor:would_{shadow.lower()}", *warnings
                ),
                confirmation_id=confirmation_id,
            )
            monitored_result: ToolResult | None = None
            if execute_tool and gate_reason is None:
                monitored_result = self.tools.execute(
                    plan.tool_name,
                    approval_token=self._tool_approval_token,
                    **plan.arguments,
                )
            return EnforcementOutcome(
                decision=monitor_decision,
                ids_score=ids_score,
                drift_velocity=vel,
                ids_components=ids_components,
                hard_rule_violation=None,
                recovery_system_message=None,
                recovery_user_message=None,
                tool_result=monitored_result,
                ids_decision=shadow,
                confirmation_id=confirmation_id,
                confirmation_reason=gate_reason,
                warnings=warnings,
            )

        if confirmation_id is not None and ids_score >= self.ids_warn_threshold:
            # The IDS stops the call before execution, so nothing awaits confirmation.
            with self._pending_lock:
                self._pending_confirmations.pop(confirmation_id, None)
                self._dead_confirmations.pop(confirmation_id, None)
            gate_reason, confirmation_id = None, None

        if ids_score >= self.ids_block_threshold:
            audit("BLOCK", False, sync_log=True)
            return EnforcementOutcome(
                decision="BLOCK",
                ids_score=ids_score,
                drift_velocity=vel,
                ids_components=ids_components,
                hard_rule_violation=None,
                recovery_system_message=None,
                recovery_user_message=None,
                tool_result=None,
            )

        preemptive = vel > self.drift_velocity_threshold and ids_score < self.ids_warn_threshold

        if ids_score >= self.ids_warn_threshold:
            audit("WARN", True, sync_log=True)
            return EnforcementOutcome(
                decision="NEEDS_RECOVERY",
                ids_score=ids_score,
                drift_velocity=vel,
                ids_components=ids_components,
                hard_rule_violation=None,
                recovery_system_message=reanchoring_system_message(c),
                recovery_user_message=reanchoring_user_nudge(
                    c,
                    reason=f"IDS {ids_score:.3f} in warn zone (>={self.ids_warn_threshold})",
                ),
                tool_result=None,
            )

        decision: Decision
        if gate_reason is not None:
            decision = "NEEDS_CONFIRMATION"
        elif preemptive:
            decision = "PREEMPTIVE_WARN"
        else:
            decision = "PASS"
        audit(
            decision,
            False,
            sync_log=self.log_async is None or gate_reason is not None,
            failure_reason=_join_reasons(gate_reason, *warnings),
            confirmation_id=confirmation_id,
        )

        tool_result: ToolResult | None = None
        if execute_tool and gate_reason is None:
            tool_result = self.tools.execute(
                plan.tool_name,
                approval_token=self._tool_approval_token,
                **plan.arguments,
            )

        return EnforcementOutcome(
            decision=decision,
            ids_score=ids_score,
            drift_velocity=vel,
            ids_components=ids_components,
            hard_rule_violation=None,
            recovery_system_message=None,
            recovery_user_message=None,
            tool_result=tool_result,
            confirmation_id=confirmation_id,
            confirmation_reason=gate_reason,
            warnings=warnings,
        )