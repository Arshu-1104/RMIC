"""unlisted_tools (v0.4.2): send tools outside allowed_actions to human
confirmation instead of blocking them. Opt-in; forbidden tools always block."""

from __future__ import annotations

import warnings
from typing import Any

import pytest

from rmic_guard import ConfirmationNotFoundError, Guard, InvalidContractError, load_contract, load_example_contract


def _contract(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "agent_id": "bank-bot",
        "role_name": "Bank Bot",
        "sector": "finance",
        "semantic_anchors": ["I check balances and transfer funds."],
        "allowed_actions": ["transfer_funds", "check_balance"],
        "forbidden_actions": ["admin_login"],
        "parameter_constraints": {"amount": {"min": 0.01, "max": 50000, "type": "float"}},
    }
    data.update(extra)
    return data


def _guard(**extra: Any) -> tuple[Guard, list[str]]:
    ran: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        guard = Guard(_contract(**extra))
    for name in ("transfer_funds", "check_balance", "export_statement", "admin_login"):
        guard.register(name, lambda _n=name, **kw: ran.append(_n) or {"ok": _n})
    return guard, ran


def test_default_still_blocks_unlisted_tools() -> None:
    guard, ran = _guard()
    r = guard.check("export_statement", month="May")
    assert r.decision == "BLOCK" and r.reason == "tool_not_allowed" and ran == []


def test_explicit_block_is_the_default_behaviour() -> None:
    guard, ran = _guard(unlisted_tools="block")
    assert guard.check("export_statement").reason == "tool_not_allowed" and ran == []


def test_confirm_parks_an_unlisted_tool_without_running_it() -> None:
    guard, ran = _guard(unlisted_tools="confirm")
    r = guard.check("export_statement", month="May")
    assert r.decision == "NEEDS_CONFIRMATION" and not r.allowed
    assert r.reason == "unlisted_tool:export_statement"
    assert r.confirmation_id and ran == []


def test_confirmed_unlisted_tool_runs_exactly_once() -> None:
    guard, ran = _guard(unlisted_tools="confirm")
    cid = guard.check("export_statement", month="May").confirmation_id
    done = guard.confirm(cid)
    assert done.decision == "CONFIRMED" and done.executed and ran == ["export_statement"]
    with pytest.raises(ConfirmationNotFoundError):
        guard.confirm(cid)
    assert ran == ["export_statement"]


def test_forbidden_tools_still_block_in_confirm_mode() -> None:
    guard, ran = _guard(unlisted_tools="confirm")
    r = guard.check("admin_login")
    assert r.decision == "BLOCK" and r.reason == "forbidden_tool" and ran == []


def test_other_hard_rules_still_apply_to_unlisted_tools() -> None:
    guard, ran = _guard(unlisted_tools="confirm", data_scope={"accessible": [], "prohibited": ["tax_records"]})
    r = guard.check("export_statement", amount=999_999)
    assert r.reason == "parameter_constraint:amount:above_max"
    r = guard.check("export_statement", data="tax_records")
    assert r.reason == "data_scope:prohibited:tax_records"
    assert ran == []


def test_listed_tools_are_unaffected() -> None:
    guard, ran = _guard(unlisted_tools="confirm")
    r = guard.check("check_balance")
    assert r.decision == "PASS" and ran == ["check_balance"]


def test_cancelled_unlisted_call_never_runs() -> None:
    guard, ran = _guard(unlisted_tools="confirm")
    cid = guard.check("export_statement").confirmation_id
    assert guard.pending_confirmations()[0].reason == "unlisted_tool:export_statement"
    guard.cancel(cid)
    with pytest.raises(ConfirmationNotFoundError):
        guard.confirm(cid)
    assert ran == []


def test_unlisted_confirmation_is_audited(tmp_path) -> None:
    log = tmp_path / "audit.jsonl"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        guard = Guard(_contract(unlisted_tools="confirm"), audit_log=log)
    guard.register("export_statement", lambda **kw: "ok")
    cid = guard.check("export_statement").confirmation_id
    guard.confirm(cid)
    text = log.read_text()
    assert '"NEEDS_CONFIRMATION"' in text and "unlisted_tool:export_statement" in text and '"CONFIRMED"' in text
    assert guard.verify_log()


@pytest.mark.parametrize("value", ["allow", "Confirm", "", True, 1])
def test_invalid_values_are_rejected_at_load(value: Any) -> None:
    with pytest.raises(InvalidContractError, match="unlisted_tools"):
        Guard(_contract(unlisted_tools=value))


def test_field_is_hashed_and_round_trips(tmp_path) -> None:
    import json

    from rmic_guard import ContractIntegrityError, RMICContract

    a = RMICContract.create(**_contract(unlisted_tools="confirm"), require_embedding=False)
    b = RMICContract.create(**_contract(), require_embedding=False)
    assert a.contract_hash != b.contract_hash
    path = tmp_path / "c.json"
    data = a.to_dict()
    path.write_text(json.dumps(data))
    loaded = load_contract(path)
    assert loaded.unlisted_tools == "confirm" and loaded.contract_hash == a.contract_hash
    data["unlisted_tools"] = "block"  # tampering is detected
    path.write_text(json.dumps(data))
    with pytest.raises(ContractIntegrityError):
        load_contract(path)


def test_bundled_contracts_do_not_enable_it() -> None:
    for name in ("financial_agent", "financial_agent_hardened", "support_agent"):
        assert load_example_contract(name).unlisted_tools is None
