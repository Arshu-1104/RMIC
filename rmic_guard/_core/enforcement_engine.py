"""
Dual enforcement between reasoning output and tool execution.

Pass 1: hard rules (forbidden tools, argument rules, parameter bounds, data
        scope, contract deny patterns).
Pass 2: IDS composite; block only when IDS >= block threshold.
Before a tool executes: contract confirm_above limits turn the call into
NEEDS_CONFIRMATION; confirm(confirmation_id) executes it exactly once.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from rmic_guard._core.audit_ledger import AuditEntry, AuditLedger, hash_text
from rmic_guard._core.contract_loader import RMICContract
from rmic_guard._core.exceptions import ConfirmationNotFoundError
from rmic_guard._core.hard_rules import check_argument_rules, confirmation_reason, deny_pattern_matches
from rmic_guard._core.ids_engine import IDSEngine
from rmic_guard._core.recovery_engine import reanchoring_system_message, reanchoring_user_nudge
from rmic_guard._core.planning import PlannedToolCall
from rmic_guard._core.tool_layer import ToolRegistry, ToolResult
from rmic_guard._utils.config import load_user_config

__all__ = ["EnforcementEngine", "EnforcementMode", "EnforcementOutcome"]

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
    # Contract deny_patterns with action "warn" that matched (the call proceeds).
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


class EnforcementEngine:
    def __init__(
        self,
        contract: RMICContract,
        tools: ToolRegistry,
        ledger: AuditLedger | None = None,
        log_async: Callable[[AuditEntry], None] | None = None,
    ) -> None:
        self.contract = contract
        self.tools = tools
        self.ledger = ledger
        self.log_async = log_async
        self._tool_approval_token = tools.issue_approval_token()
        # confirmation_id -> plan awaiting confirm(); each id is removed on use.
        self._pending_confirmations: dict[str, PlannedToolCall] = {}
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
            self._pending_confirmations[confirmation_id] = plan
        return reason, confirmation_id, warnings

    @property
    def pending_confirmations(self) -> int:
        """Number of NEEDS_CONFIRMATION calls not yet confirmed."""
        with self._pending_lock:
            return len(self._pending_confirmations)

    def pending_plan(self, confirmation_id: str) -> PlannedToolCall | None:
        """The call waiting under confirmation_id (None if unknown or already used)."""
        with self._pending_lock:
            return self._pending_confirmations.get(confirmation_id)

    def confirm(self, confirmation_id: str, *, execute_tool: bool = True) -> EnforcementOutcome:
        """Execute a call that returned NEEDS_CONFIRMATION. Single use: the id
        is consumed before anything runs, so a second confirm() raises
        ConfirmationNotFoundError. Hard rules are re-checked; the confirmation
        is written to the audit log (decision CONFIRMED, same confirmation_id
        as the NEEDS_CONFIRMATION entry)."""
        with self._pending_lock:
            plan = self._pending_confirmations.pop(confirmation_id, None)
        if plan is None:
            raise ConfirmationNotFoundError(
                f"No pending confirmation {confirmation_id!r}: it was never issued by this engine "
                "or has already been used."
            )
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
                    failure_reason=hard,
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