"""Regression tests for limit bypasses found in 0.4.1.

1. Non-finite amounts (NaN, inf) passed min/max and confirm_above, because every
   comparison with NaN is False. Booleans passed as 1.0 / 0.0.
2. Renaming an argument (Amount, AMOUNT, "amount ") skipped parameter bounds,
   confirm_above, session_limits and argument patterns, which were looked up by
   exact name.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest

from rmic_guard import Guard, load_example_contract


def _contract(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "agent_id": "bank-bot",
        "role_name": "Bank Bot",
        "sector": "finance",
        "semantic_anchors": ["I check balances and transfer funds."],
        "allowed_actions": ["transfer_funds", "check_balance"],
        "forbidden_actions": ["admin_login"],
        "parameter_constraints": {"amount": {"min": 0.01, "max": 50000, "type": "float", "confirm_above": 10000}},
    }
    data.update(extra)
    return data


def _guard(**extra: Any) -> tuple[Guard, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        guard = Guard(_contract(**extra))
    guard.register("transfer_funds", lambda **kw: calls.append(kw) or {"ok": True})
    return guard, calls


# ── 1. non-finite and boolean values ────────────────────────────────────────


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "nan", "NaN", "inf", "-Infinity"])
def test_non_finite_amount_blocks(value: Any) -> None:
    guard, calls = _guard()
    r = guard.check("transfer_funds", amount=value, to_account="4321")
    assert r.decision == "BLOCK"
    assert r.reason == "parameter_constraint:amount:not_finite"
    assert calls == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "nan"])
def test_non_finite_int_parameter_blocks_without_crashing(value: Any) -> None:
    guard, calls = _guard(parameter_constraints={"count": {"min": 1, "max": 10, "type": "int"}})
    r = guard.check("transfer_funds", count=value, to_account="4321")
    assert r.decision == "BLOCK" and r.reason == "parameter_constraint:count:not_finite"


@pytest.mark.parametrize("value", [True, False])
def test_boolean_amount_blocks(value: bool) -> None:
    guard, calls = _guard()
    r = guard.check("transfer_funds", amount=value, to_account="4321")
    assert r.decision == "BLOCK" and r.reason == "parameter_constraint:amount:not_numeric"
    assert calls == []


@pytest.mark.parametrize("value", [500, 500.5, "500", "1e3", 0.01, 10000])
def test_ordinary_amounts_still_pass(value: Any) -> None:
    guard, calls = _guard()
    r = guard.check("transfer_funds", amount=value, to_account="4321")
    assert r.decision == "PASS" and r.executed


def test_bundled_financial_contract_blocks_nan() -> None:
    guard = Guard(load_example_contract("financial_agent"))
    r = guard.check("transfer_funds", amount=float("nan"), to_account="4321")
    assert r.decision == "BLOCK" and r.reason == "parameter_constraint:amount:not_finite"


# ── 2. renamed arguments ────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["Amount", "AMOUNT", " amount ", "AmOuNt"])
def test_renamed_argument_is_still_bounded(name: str) -> None:
    guard, calls = _guard()
    r = guard.check("transfer_funds", arguments={name: 999_999, "to_account": "4321"})
    assert r.decision == "BLOCK" and r.reason == "parameter_constraint:amount:above_max"
    assert calls == []


def test_renamed_argument_still_needs_confirmation() -> None:
    guard, calls = _guard()
    r = guard.check("transfer_funds", Amount=20_000, to_account="4321")
    assert r.decision == "NEEDS_CONFIRMATION" and r.reason == "confirm_above:amount"
    assert calls == []


def test_each_matching_argument_is_checked() -> None:
    guard, calls = _guard()
    r = guard.check("transfer_funds", amount=10, Amount=999_999, to_account="4321")
    assert r.decision == "BLOCK" and r.reason == "parameter_constraint:amount:above_max"


def test_hyphen_and_space_spellings_match_underscore_names() -> None:
    guard, _ = _guard(
        parameter_constraints={"max_results": {"min": 1, "max": 50, "type": "int"}},
        allowed_actions=["transfer_funds"],
    )
    for name in ("max-results", "max results", "Max_Results"):
        r = guard.check("transfer_funds", arguments={name: 500})
        assert r.decision == "BLOCK" and r.reason == "parameter_constraint:max_results:above_max", name


def test_renamed_argument_counts_toward_session_limit() -> None:
    guard, calls = _guard(session_limits={"transfer_funds": {"param": "amount", "max_total": 15000}})
    s = guard.session("user-1")
    assert s.check("transfer_funds", amount=9000, to_account="4321").decision == "PASS"
    r = s.check("transfer_funds", Amount=9000, to_account="4321")
    assert r.decision == "BLOCK" and r.reason == "session_limit:transfer_funds:amount"
    assert s.session_totals == {"transfer_funds:amount": 9000.0}


def test_renamed_arguments_add_to_session_total() -> None:
    guard, _ = _guard(session_limits={"transfer_funds": {"param": "amount", "max_total": 15000}})
    s = guard.session("user-2")
    assert s.check("transfer_funds", AMOUNT=5000, to_account="4321").decision == "PASS"
    assert s.session_totals == {"transfer_funds:amount": 5000.0}


def test_renamed_argument_is_still_pattern_checked() -> None:
    guard, calls = _guard(argument_rules={"transfer_funds": {"patterns": {"to_account": r"\d{4}"}}})
    r = guard.check("transfer_funds", amount=10, To_Account="crypto-wallet")
    assert r.decision == "BLOCK" and r.reason == "argument_pattern:transfer_funds:to_account"
    assert calls == []


def test_allowed_args_accepts_other_spellings_of_listed_names() -> None:
    guard, _ = _guard(argument_rules={"transfer_funds": {"allowed_args": ["amount", "to_account"]}})
    assert guard.check("transfer_funds", Amount=10, to_account="4321").decision == "PASS"
    r = guard.check("transfer_funds", amount=10, to_account="4321", memo="x")
    assert r.reason == "argument_not_allowed:transfer_funds:memo"


def test_hardened_contract_blocks_renamed_large_transfer() -> None:
    guard = Guard(load_example_contract("financial_agent_hardened"))
    for name in ("Amount", "AMOUNT"):
        r = guard.check("transfer_funds", arguments={name: 999_999, "to_account": "4321"})
        assert r.decision == "BLOCK" and r.reason == "parameter_constraint:amount:above_max", name
