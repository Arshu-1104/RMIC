"""Contract -> AgentSpec / Progent translation used by experiment/head_to_head/.

These run without the frameworks installed: they check the generated policies,
not the frameworks themselves (run_h2h.py needs scripts/fetch_head_to_head_frameworks.py).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiment" / "head_to_head"))
sys.path.insert(0, str(REPO / "experiment" / "eval_real_data"))

import run_h2h as H  # noqa: E402


@pytest.fixture(scope="module")
def hardened():
    return H.contract_for("financial_agent_hardened")


def test_progent_policy_allows_only_allowed_tools(hardened) -> None:
    policy = H.progent_policy(hardened, {"transfer_funds": {"amount", "to_account"}})
    assert set(policy) == set(hardened.allowed_actions)
    assert not set(policy) & set(hardened.forbidden_actions)


def test_progent_bounds_and_confirmation(hardened) -> None:
    policy = H.progent_policy(hardened, {"transfer_funds": {"amount", "to_account"}})
    allow = [p for p in policy["transfer_funds"] if p[1] == 0]
    forbid = [p for p in policy["transfer_funds"] if p[1] == 1]
    assert allow[0][2]["amount"] == {"type": "number", "minimum": 0.01, "maximum": 50000.0}
    assert allow[0][2]["to_account"]["pattern"].startswith("^(?:") and allow[0][2]["to_account"]["pattern"].endswith(")$")
    assert forbid == [(1, 1, {"amount": {"type": "number", "exclusiveMinimum": 10000.0, "maximum": 50000.0}}, 2)]


def test_progent_confirmation_only_on_tools_that_take_the_parameter(hardened) -> None:
    policy = H.progent_policy(hardened, {"transfer_funds": {"amount"}})
    assert all(p[1] == 0 for p in policy["check_balance"])


def test_agentspec_rules_deny_unlisted_tools_and_check_allowed_ones(hardened) -> None:
    tools = sorted(set(hardened.allowed_actions) | set(hardened.forbidden_actions))
    rules = H.agentspec_rules(hardened, tools)
    denies = [r for r in rules if "enforce skip" in r and "check true" in r]
    assert len(denies) == len(hardened.forbidden_actions)
    for tool in hardened.allowed_actions:
        assert any(f"trigger {tool}\ncheck rmic_confirm__{tool}\nenforce user_inspection" in r for r in rules)


class _Act:
    def __init__(self, name: str, args: dict) -> None:
        self.name, self.input = name, json.dumps(args)


def test_agentspec_predicates(hardened) -> None:
    p = H.agentspec_predicates(hardened)
    bounds, pattern = p["rmic_bounds__transfer_funds"], p["rmic_pattern__transfer_funds"]
    session, confirm = p["rmic_session__transfer_funds"], p["rmic_confirm__transfer_funds"]
    ok = json.dumps({"amount": 500, "to_account": "4321"})
    assert not bounds("", ok, []) and not pattern("", ok, []) and not session("", ok, []) and not confirm("", ok, [])
    assert bounds("", json.dumps({"amount": 60000}), [])
    assert bounds("", json.dumps({"amount": math.nan}), [])
    assert pattern("", json.dumps({"to_account": "IBAN GB29NWBK60161331926819"}), [])
    assert confirm("", json.dumps({"amount": 20000}), [])
    steps = [(_Act("transfer_funds", {"amount": 9000}), "ok")] * 5
    assert session("", json.dumps({"amount": 9000}), steps)
    assert not session("", json.dumps({"amount": 5000}), steps)


def test_committed_results_agree_across_frameworks() -> None:
    rows = H.read_csv(REPO / "experiment" / "head_to_head" / "items.csv")
    by: dict[tuple, set] = {}
    for r in rows:
        by.setdefault((r["set"], r["contract"], r["item_id"]), set()).add(r["outcome"])
    assert len(by) == 145 + 87 + 13_085
    assert all(len(v) == 1 for v in by.values())
