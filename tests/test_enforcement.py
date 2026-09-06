from __future__ import annotations

from core.contract_loader import RMICContract
from core.enforcement_engine import EnforcementEngine
from core.planning import PlannedToolCall
from core.tool_layer import ToolRegistry


def _contract(**overrides) -> RMICContract:
    defaults = dict(
        agent_id="a",
        role_name="A",
        sector="s",
        semantic_anchors=["I do research."],
        allowed_actions=["web_search"],
        forbidden_actions=["delete_data"],
        parameter_constraints={"amount": {"min": 0, "max": 100, "type": "float"}},
        data_scope={"prohibited": ["medical_records"]},
        require_embedding=False,
    )
    defaults.update(overrides)
    return RMICContract.create(**defaults)


class TestHardRuleAllow:
    def test_allowed_tool_passes(self) -> None:
        calls: list[str] = []
        tools = ToolRegistry()
        tools.register("web_search", lambda **kw: calls.append("ran") or {"ok": True})
        engine = EnforcementEngine(contract=_contract(), tools=tools)

        plan = PlannedToolCall(tool_name="web_search", arguments={}, raw_text="search")
        outcome = engine.evaluate_and_maybe_execute(plan, recent_ids=[], enforcement_mode="hard_rules_only")

        assert outcome.decision == "PASS"
        assert outcome.hard_rule_violation is None
        assert calls == ["ran"]
        assert outcome.tool_result is not None and outcome.tool_result.ok


class TestHardRuleForbidden:
    def test_forbidden_tool_blocks(self) -> None:
        tools = ToolRegistry()
        tools.register("delete_data", lambda **kw: {"deleted": True})
        engine = EnforcementEngine(contract=_contract(), tools=tools)

        plan = PlannedToolCall(tool_name="delete_data", arguments={}, raw_text="delete everything")
        outcome = engine.evaluate_and_maybe_execute(plan, recent_ids=[], enforcement_mode="hard_rules_only")

        assert outcome.decision == "BLOCK"
        assert outcome.hard_rule_violation == "forbidden_tool"

    def test_tool_is_not_executed_after_block(self) -> None:
        calls: list[str] = []
        tools = ToolRegistry()
        tools.register("delete_data", lambda **kw: calls.append("ran"))
        engine = EnforcementEngine(contract=_contract(), tools=tools)

        plan = PlannedToolCall(tool_name="delete_data", arguments={}, raw_text="delete everything")
        outcome = engine.evaluate_and_maybe_execute(
            plan, recent_ids=[], enforcement_mode="hard_rules_only", execute_tool=True
        )

        assert outcome.decision == "BLOCK"
        assert outcome.tool_result is None
        assert calls == []  # never invoked, regardless of execute_tool=True

    def test_tool_not_in_allow_list_blocks(self) -> None:
        tools = ToolRegistry()
        tools.register("unlisted_tool", lambda **kw: {"ok": True})
        engine = EnforcementEngine(contract=_contract(), tools=tools)

        plan = PlannedToolCall(tool_name="unlisted_tool", arguments={}, raw_text="do something else")
        outcome = engine.evaluate_and_maybe_execute(plan, recent_ids=[], enforcement_mode="hard_rules_only")

        assert outcome.decision == "BLOCK"
        assert outcome.hard_rule_violation == "tool_not_allowed"


class TestParameterConstraints:
    def test_parameter_above_max_blocks(self) -> None:
        tools = ToolRegistry()
        tools.register("web_search", lambda **kw: {"ok": True})
        engine = EnforcementEngine(contract=_contract(), tools=tools)

        plan = PlannedToolCall(tool_name="web_search", arguments={"amount": 999}, raw_text="search")
        outcome = engine.evaluate_and_maybe_execute(plan, recent_ids=[], enforcement_mode="hard_rules_only")

        assert outcome.decision == "BLOCK"
        assert outcome.hard_rule_violation == "parameter_constraint:amount:above_max"

    def test_parameter_below_min_blocks(self) -> None:
        tools = ToolRegistry()
        tools.register("web_search", lambda **kw: {"ok": True})
        engine = EnforcementEngine(contract=_contract(), tools=tools)

        plan = PlannedToolCall(tool_name="web_search", arguments={"amount": -5}, raw_text="search")
        outcome = engine.evaluate_and_maybe_execute(plan, recent_ids=[], enforcement_mode="hard_rules_only")

        assert outcome.decision == "BLOCK"
        assert outcome.hard_rule_violation == "parameter_constraint:amount:below_min"

    def test_parameter_within_bounds_passes(self) -> None:
        tools = ToolRegistry()
        tools.register("web_search", lambda **kw: {"ok": True})
        engine = EnforcementEngine(contract=_contract(), tools=tools)

        plan = PlannedToolCall(tool_name="web_search", arguments={"amount": 50}, raw_text="search")
        outcome = engine.evaluate_and_maybe_execute(plan, recent_ids=[], enforcement_mode="hard_rules_only")

        assert outcome.decision == "PASS"


class TestDataScope:
    def test_prohibited_data_category_blocks(self) -> None:
        tools = ToolRegistry()
        tools.register("web_search", lambda **kw: {"ok": True})
        engine = EnforcementEngine(contract=_contract(), tools=tools)

        plan = PlannedToolCall(
            tool_name="web_search",
            arguments={},
            raw_text="search",
            data_categories_accessed=("medical_records",),
        )
        outcome = engine.evaluate_and_maybe_execute(plan, recent_ids=[], enforcement_mode="hard_rules_only")

        assert outcome.decision == "BLOCK"
        assert outcome.hard_rule_violation == "data_scope:prohibited:medical_records"


class TestFullModeUsesIds:
    def test_full_mode_returns_a_valid_decision_and_ids_score(self) -> None:
        # Uses the deterministic embedding backend from tests/conftest.py.
        contract = _contract(require_embedding=True)
        tools = ToolRegistry()
        tools.register("web_search", lambda **kw: {"ok": True})
        engine = EnforcementEngine(contract=contract, tools=tools)

        plan = PlannedToolCall(tool_name="web_search", arguments={}, raw_text="search for papers on drift")
        outcome = engine.evaluate_and_maybe_execute(plan, recent_ids=[], enforcement_mode="full")

        assert outcome.decision in ("PASS", "WARN", "NEEDS_RECOVERY", "BLOCK", "PREEMPTIVE_WARN")
        assert 0.0 <= outcome.ids_score <= 1.0
