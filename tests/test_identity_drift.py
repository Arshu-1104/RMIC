from __future__ import annotations

from core.contract_loader import RMICContract
from core.ids_engine import IDSEngine
from core.ids_metric import compute_ids_components, trajectory_curvature


def _sealed_contract() -> RMICContract:
    # Uses the deterministic embedding backend from tests/conftest.py.
    return RMICContract.create(
        agent_id="a",
        role_name="A",
        sector="s",
        semantic_anchors=["I perform research and information gathering."],
        allowed_actions=["web_search"],
        forbidden_actions=["delete_data"],
        require_embedding=True,
    )


class TestIdsComponentsShape:
    def test_all_components_present_and_bounded(self) -> None:
        contract = _sealed_contract()
        components = compute_ids_components(
            "search the web for papers on identity drift",
            contract.anchor_embedding,
            allowed_topics=list(contract.semantic_anchors),
            forbidden_topics=list(contract.forbidden_actions),
            recent_ids=[],
            tool_call_history=["web_search"],
            allowed_actions=contract.allowed_actions,
        )
        expected_keys = {
            "role_distance", "semantic_grounding", "trajectory_curvature", "base_ids",
            "mahalanobis", "kl_divergence", "js_divergence", "wasserstein", "hellinger",
            "tool_frequency",
        }
        assert expected_keys.issubset(components.keys())
        for key, value in components.items():
            assert 0.0 <= value <= 1.0, f"{key}={value} out of [0, 1]"

    def test_base_ids_is_weighted_combination(self) -> None:
        contract = _sealed_contract()
        components = compute_ids_components(
            "I am now going to delete the production database",
            contract.anchor_embedding,
            allowed_topics=list(contract.semantic_anchors),
            forbidden_topics=list(contract.forbidden_actions),
            recent_ids=[],
            tool_call_history=[],
            allowed_actions=contract.allowed_actions,
        )
        expected = (
            0.4 * components["role_distance"]
            + 0.4 * components["semantic_grounding"]
            + 0.2 * components["trajectory_curvature"]
        )
        assert abs(components["base_ids"] - expected) < 1e-6


class TestTrajectoryCurvature:
    def test_empty_or_single_history_is_zero(self) -> None:
        assert trajectory_curvature([]) == 0.0
        assert trajectory_curvature([0.5]) == 0.0

    def test_volatile_history_scores_higher_than_stable_history(self) -> None:
        stable = trajectory_curvature([0.2, 0.2, 0.2, 0.2])
        volatile = trajectory_curvature([0.1, 0.9, 0.1, 0.9])
        assert volatile > stable


class TestToolFrequencyDrift:
    def test_all_allowed_tools_scores_zero(self) -> None:
        from core.ids_metric import tool_frequency_drift

        score = tool_frequency_drift(
            tool_call_history=["web_search", "web_search", "web_search"],
            allowed_actions=("web_search",),
        )
        assert score == 0.0

    def test_all_disallowed_tools_scores_one(self) -> None:
        from core.ids_metric import tool_frequency_drift

        score = tool_frequency_drift(
            tool_call_history=["delete_data", "delete_data"],
            allowed_actions=("web_search",),
        )
        assert score == 1.0


class TestIdsEngineWrapper:
    def test_score_matches_compute_ids_components(self) -> None:
        contract = _sealed_contract()
        text = "search for identity drift papers"
        direct = compute_ids_components(
            text,
            contract.anchor_embedding,
            allowed_topics=list(contract.semantic_anchors),
            forbidden_topics=list(contract.forbidden_actions),
            recent_ids=[],
            tool_call_history=["web_search"],
            allowed_actions=contract.allowed_actions,
        )
        via_engine = IDSEngine().score(
            text,
            anchor_embedding=contract.anchor_embedding,
            allowed_topics=list(contract.semantic_anchors),
            forbidden_topics=list(contract.forbidden_actions),
            recent_ids=[],
            tool_call_history=["web_search"],
            allowed_actions=contract.allowed_actions,
        )
        assert direct == via_engine
