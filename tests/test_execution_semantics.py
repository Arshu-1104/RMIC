"""Execution semantics of every decision state (docs/execution_semantics.md).

For each decision Guard can return, these tests pin down whether the tool runs, what
GuardResult reports, and that the decision is written to the signed audit log. The IDS score
is stubbed so every state is reached deterministically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import rmic_guard._core.enforcement_engine as engine_mod
from rmic_guard import Guard, ToolRegistry

CONTRACT: dict[str, Any] = {
    "agent_id": "bank-bot",
    "role_name": "Bank Bot",
    "sector": "finance",
    "semantic_anchors": ["I check balances and transfer funds within approved limits."],
    "allowed_actions": ["transfer_funds", "check_balance"],
    "forbidden_actions": ["admin_login"],
    "parameter_constraints": {"amount": {"min": 0.01, "max": 50000, "confirm_above": 10000, "type": "float"}},
    "ids_warn_threshold": 0.35,
    "ids_block_threshold": 0.60,
    "drift_velocity_threshold": 0.05,
}


@pytest.fixture
def ids(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Queue of IDS scores the engine will return, one per scored call (default 0.0)."""
    queue: list[float] = []

    def fake(contract: Any, plan: Any, recent_ids: list[float], tool_call_history: Any = None) -> tuple[float, dict]:
        score = queue.pop(0) if queue else 0.0
        return score, {"base_ids": score, "role_distance": score, "semantic_grounding": score,
                       "trajectory_curvature": 0.0}

    monkeypatch.setattr(engine_mod, "_ids_on_plan", fake)
    return queue


def _guard(tmp_path: Path, semantic: Any = True) -> tuple[Guard, list[dict]]:
    calls: list[dict] = []
    guard = Guard(CONTRACT, semantic=semantic, audit_log=tmp_path / "audit.jsonl")
    guard.register("transfer_funds", lambda **kw: calls.append(kw) or {"sent": kw["amount"]})
    guard.register("check_balance", lambda **kw: calls.append(kw) or {"balance": 1})
    return guard, calls


def _audit(tmp_path: Path) -> list[dict]:
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["entry"] for line in lines]


# (name, semantic mode, queued IDS scores, calls: [(tool, args)]) -> expected last decision,
# whether its tool ran, GuardResult.allowed, and the reason.
CASES = [
    ("pass", True, [0.10], [("check_balance", {})], "PASS", True, True, None),
    ("preemptive_warn", True, [0.00, 0.20], [("check_balance", {}), ("check_balance", {})],
     "PREEMPTIVE_WARN", True, True, "drift_velocity_exceeded"),
    ("needs_recovery", True, [0.45], [("check_balance", {})], "NEEDS_RECOVERY", False, False,
     "ids_warn_threshold_reached"),
    ("ids_block", True, [0.70], [("check_balance", {})], "BLOCK", False, False, "ids_block_threshold_exceeded"),
    ("hard_block", True, [0.00], [("admin_login", {})], "BLOCK", False, False, "forbidden_tool"),
    ("needs_confirmation", True, [0.00], [("transfer_funds", {"amount": 20000, "to_account": "1234"})],
     "NEEDS_CONFIRMATION", False, False, "confirm_above:amount"),
    ("monitor_never_blocks_on_ids", "monitor", [0.90], [("check_balance", {})], "PASS", True, True, None),
    ("hard_rules_only", False, [], [("check_balance", {})], "PASS", True, True, None),
]


@pytest.mark.parametrize("name, semantic, scores, calls, decision, ran, allowed, reason", CASES,
                         ids=[c[0] for c in CASES])
def test_each_decision_state(tmp_path: Path, ids: list[float], name: str, semantic: Any, scores: list[float],
                             calls: list, decision: str, ran: bool, allowed: bool, reason: str | None) -> None:
    ids.extend(scores)
    guard, executed = _guard(tmp_path, semantic)
    for tool, args in calls[:-1]:
        guard.check(tool, arguments=args)
    before = len(executed)
    tool, args = calls[-1]
    r = guard.check(tool, arguments=args)
    assert (r.decision, r.executed, r.allowed, r.reason) == (decision, ran, allowed, reason)
    assert len(executed) - before == (1 if ran else 0)
    # Every check, allowed or not, is one signed audit entry with the same decision.
    log = _audit(tmp_path)
    logged = {"NEEDS_RECOVERY": "WARN"}.get(decision, decision)  # the audit log names this state WARN
    assert len(log) == len(calls) and log[-1]["decision"] == logged
    assert guard.verify_log()


def test_monitor_records_what_enforcement_would_have_done(tmp_path: Path, ids: list[float]) -> None:
    ids.append(0.90)
    guard, executed = _guard(tmp_path, "monitor")
    r = guard.check("check_balance")
    assert r.ids_decision == "BLOCK" and r.executed and len(executed) == 1
    assert "monitor:would_block" in (_audit(tmp_path)[-1]["failure_reason"] or "")


def test_confirmed_runs_exactly_once(tmp_path: Path, ids: list[float]) -> None:
    guard, executed = _guard(tmp_path)
    pending = guard.check("transfer_funds", amount=20000, to_account="1234")
    assert pending.decision == "NEEDS_CONFIRMATION" and executed == []
    done = guard.confirm(pending.confirmation_id)
    assert (done.decision, done.executed, done.allowed) == ("CONFIRMED", True, True) and len(executed) == 1
    assert [e["decision"] for e in _audit(tmp_path)] == ["NEEDS_CONFIRMATION", "CONFIRMED"]
    assert _audit(tmp_path)[0]["confirmation_id"] == _audit(tmp_path)[1]["confirmation_id"]


def test_run_never_executes_a_plan_still_in_the_warn_zone(tmp_path: Path, ids: list[float]) -> None:
    class Planner:
        def plan_tool_call(self, *args: Any, **kwargs: Any) -> Any:
            from rmic_guard import PlannedToolCall

            return PlannedToolCall(tool_name="check_balance", arguments={}, raw_text="x",
                                   data_categories_accessed=(), user_message="x")

    ids.extend([0.45, 0.45])  # first plan and the re-anchored re-plan both land in the warn zone
    guard, executed = _guard(tmp_path)
    r = guard.run("what's my balance", llm=Planner(), max_recovery=1)
    assert (r.decision, r.executed, r.recovery_attempted) == ("BLOCK", False, True)
    assert r.reason == "recovery_failed:ids_warn_threshold_reached" and executed == []


def test_registry_refuses_execution_without_the_engines_approval() -> None:
    calls: list[int] = []
    registry = ToolRegistry()
    registry.register("transfer_funds", lambda **kw: calls.append(1))
    for token in (None, "guessed-token"):
        result = registry.execute("transfer_funds", approval_token=token, amount=1)
        assert not result.ok and result.error == "execution_not_approved_by_enforcement_engine"
    assert calls == []


@pytest.mark.parametrize(
    "tool, args, reason",
    [
        ("admin_login", {}, "forbidden_tool"),
        ("delete_everything", {}, "tool_not_allowed"),
        ("transfer_funds", {"amount": 60000, "to_account": "1234"}, "parameter_constraint:amount:above_max"),
    ],
)
def test_full_mode_preserves_every_hard_rule_block(tmp_path: Path, ids: list[float], tool: str, args: dict,
                                                   reason: str) -> None:
    """For identical inputs, semantic scoring can only add blocks: a hard-rule block is the
    same in hard_rules_only, full and monitor mode, whatever the IDS says."""
    for semantic in (False, True, "monitor"):
        ids[:] = [0.0]
        guard, executed = _guard(tmp_path / str(semantic), semantic)
        r = guard.check(tool, arguments=args)
        assert (r.decision, r.reason, r.executed) == ("BLOCK", reason, False), semantic
        assert executed == []
