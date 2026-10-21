"""Experimental IDS scoring v2 is opt-in per contract and leaves v1 untouched."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rmic_guard import (
    EnforcementEngine,
    Guard,
    IDSEngine,
    InvalidContractError,
    PlannedToolCall,
    RMICContract,
    ToolRegistry,
    compute_contract_hash,
    load_contract,
)
from rmic_guard._core.enforcement_engine import ids_text_and_forbidden_topics


def _kwargs(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = dict(
        agent_id="bank-bot",
        role_name="Bank Bot",
        sector="finance",
        semantic_anchors=["I check account balances.", "I transfer funds between a customer's accounts."],
        allowed_actions=["check_balance", "transfer_funds"],
        forbidden_actions=["admin_login"],
    )
    data.update(overrides)
    return data


V2 = dict(ids_scoring_version=2, forbidden_topics=["Giving personalised investment advice."])


def _plan(tool: str, message: str, **arguments: Any) -> PlannedToolCall:
    return PlannedToolCall(tool_name=tool, arguments=arguments, raw_text=message)


class TestContractFields:
    def test_v1_contract_has_no_new_keys_and_same_hash(self) -> None:
        contract = RMICContract.create(**_kwargs(), require_embedding=False)
        d = contract.to_dict()
        assert "ids_scoring_version" not in d and "forbidden_topics" not in d
        assert contract.ids_scoring_version == 1 and contract.forbidden_topics == ()
        assert compute_contract_hash(d) == contract.contract_hash

    def test_v2_contract_round_trips_through_json(self, tmp_path: Path) -> None:
        contract = RMICContract.create(**_kwargs(**V2), require_embedding=False)
        path = tmp_path / "v2.json"
        path.write_text(json.dumps(contract.to_dict()))
        loaded = load_contract(path)
        assert loaded.ids_scoring_version == 2
        assert loaded.forbidden_topics == ("Giving personalised investment advice.",)
        assert loaded.contract_hash == contract.contract_hash

    @pytest.mark.parametrize(
        "overrides, problem",
        [
            ({"ids_scoring_version": 3}, "ids_scoring_version"),
            ({"ids_scoring_version": True}, "ids_scoring_version"),
            ({"ids_scoring_version": 2}, "forbidden_topics"),
            ({"ids_scoring_version": 2, "forbidden_topics": []}, "forbidden_topics"),
            ({"ids_scoring_version": 2, "forbidden_topics": ["  "]}, "forbidden_topics"),
            ({"forbidden_topics": "not a list"}, "forbidden_topics"),
        ],
    )
    def test_invalid_v2_fields_are_rejected(self, overrides: dict[str, Any], problem: str) -> None:
        with pytest.raises(InvalidContractError, match=problem):
            RMICContract.create(**_kwargs(**overrides), require_embedding=False)


class TestIdsInputs:
    def test_v1_embeds_tool_arguments_and_message_without_forbidden_topics(self) -> None:
        contract = RMICContract.create(**_kwargs(), require_embedding=False)
        text, forbidden = ids_text_and_forbidden_topics(contract, _plan("check_balance", "balance?", account="1"))
        assert text == "check_balance {'account': '1'} balance?"
        assert forbidden == []

    def test_v2_embeds_message_only_with_contract_forbidden_topics(self) -> None:
        contract = RMICContract.create(**_kwargs(**V2), require_embedding=False)
        text, forbidden = ids_text_and_forbidden_topics(contract, _plan("check_balance", " balance? ", account="1"))
        assert text == "balance?"
        assert forbidden == ["Giving personalised investment advice."]

    def test_v2_empty_message_falls_back_to_v1_text(self) -> None:
        contract = RMICContract.create(**_kwargs(**V2), require_embedding=False)
        text, _ = ids_text_and_forbidden_topics(contract, _plan("check_balance", "   "))
        assert text.startswith("check_balance {}")


class TestEngineScores:
    def _score(self, contract: RMICContract, plan: PlannedToolCall) -> float:
        engine = EnforcementEngine(contract=contract, tools=ToolRegistry())
        out = engine.evaluate_and_maybe_execute(plan, recent_ids=[], execute_tool=False, enforcement_mode="ids_only")
        return out.ids_score

    def test_v2_score_does_not_depend_on_tool_or_arguments(self) -> None:
        contract = RMICContract.create(**_kwargs(**V2))
        a = self._score(contract, _plan("check_balance", "How much is in my savings account?"))
        b = self._score(contract, _plan("transfer_funds", "How much is in my savings account?", amount=10))
        assert a == pytest.approx(b)

    def test_v1_score_is_unchanged(self) -> None:
        contract = RMICContract.create(**_kwargs())
        plan = _plan("transfer_funds", "Pay my rent.", amount=10)
        expected = IDSEngine().score(
            "transfer_funds {'amount': 10} Pay my rent.",
            contract.anchor_embedding,
            allowed_topics=list(contract.semantic_anchors),
            forbidden_topics=[],
            recent_ids=[],
            tool_call_history=["transfer_funds"],
            allowed_actions=tuple(contract.allowed_actions),
        )["base_ids"]
        assert self._score(contract, plan) == pytest.approx(expected)

    def test_guard_runs_v2_contracts(self) -> None:
        guard = Guard(_kwargs(**V2), semantic=True)
        guard.register("check_balance", lambda: 1)
        result = guard.check("check_balance", message="What is my balance?")
        assert 0.0 <= result.ids_score <= 1.0
        assert guard.check("admin_login", message="Log me in as admin").reason == "forbidden_tool"
