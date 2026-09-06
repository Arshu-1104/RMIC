from __future__ import annotations

import pytest

from core.exceptions import InvalidContractError
from core.validation import validate_contract_dict


def _valid() -> dict:
    return {
        "agent_id": "a",
        "role_name": "A",
        "sector": "s",
        "semantic_anchors": ["I do research."],
        "allowed_actions": ["web_search"],
        "forbidden_actions": ["delete_data"],
        "data_scope": {"accessible": ["docs"], "prohibited": ["pii"], "pii_categories": []},
        "parameter_constraints": {"amount": {"min": 0, "max": 100, "type": "float"}},
        "ids_warn_threshold": 0.3,
        "ids_block_threshold": 0.6,
        "drift_velocity_threshold": 0.05,
        "contract_version": "1.0.0",
    }


class TestValidContract:
    def test_valid_contract_passes(self) -> None:
        validate_contract_dict(_valid())  # should not raise


class TestMissingRequiredField:
    @pytest.mark.parametrize("field", ["agent_id", "role_name", "sector"])
    def test_missing_field_raises(self, field: str) -> None:
        data = _valid()
        del data[field]
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any(field in p for p in exc_info.value.problems)

    def test_missing_semantic_anchors_raises(self) -> None:
        data = _valid()
        del data["semantic_anchors"]
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("semantic_anchors" in p for p in exc_info.value.problems)

    def test_empty_semantic_anchors_raises(self) -> None:
        data = _valid()
        data["semantic_anchors"] = []
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("semantic_anchors" in p for p in exc_info.value.problems)


class TestInvalidTypes:
    def test_agent_id_wrong_type_raises(self) -> None:
        data = _valid()
        data["agent_id"] = 123
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("agent_id" in p for p in exc_info.value.problems)

    def test_allowed_actions_wrong_type_raises(self) -> None:
        data = _valid()
        data["allowed_actions"] = "web_search"  # should be a list
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("allowed_actions" in p for p in exc_info.value.problems)

    def test_semantic_anchors_wrong_element_type_raises(self) -> None:
        data = _valid()
        data["semantic_anchors"] = ["ok", 5]
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("semantic_anchors" in p for p in exc_info.value.problems)


class TestInvalidThresholds:
    def test_warn_threshold_out_of_range_raises(self) -> None:
        data = _valid()
        data["ids_warn_threshold"] = 1.5
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("ids_warn_threshold" in p for p in exc_info.value.problems)

    def test_warn_greater_than_block_raises(self) -> None:
        data = _valid()
        data["ids_warn_threshold"] = 0.8
        data["ids_block_threshold"] = 0.2
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("ids_warn_threshold" in p and "ids_block_threshold" in p for p in exc_info.value.problems)

    def test_negative_velocity_threshold_raises(self) -> None:
        data = _valid()
        data["drift_velocity_threshold"] = -0.1
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("drift_velocity_threshold" in p for p in exc_info.value.problems)


class TestInvalidDataScope:
    def test_data_scope_not_object_raises(self) -> None:
        data = _valid()
        data["data_scope"] = ["not", "an", "object"]
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("data_scope" in p for p in exc_info.value.problems)

    def test_data_scope_field_wrong_type_raises(self) -> None:
        data = _valid()
        data["data_scope"] = {"accessible": "not-a-list"}
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("data_scope.accessible" in p for p in exc_info.value.problems)


class TestInvalidParameterConstraints:
    def test_parameter_constraints_not_object_raises(self) -> None:
        data = _valid()
        data["parameter_constraints"] = ["nope"]
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("parameter_constraints" in p for p in exc_info.value.problems)

    def test_parameter_constraint_min_greater_than_max_raises(self) -> None:
        data = _valid()
        data["parameter_constraints"] = {"amount": {"min": 100, "max": 10, "type": "float"}}
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("amount" in p and "min" in p for p in exc_info.value.problems)

    def test_parameter_constraint_bad_type_raises(self) -> None:
        data = _valid()
        data["parameter_constraints"] = {"amount": {"type": "string"}}
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("parameter_constraints.amount.type" in p for p in exc_info.value.problems)


class TestInvalidVersionsAndTimestamps:
    def test_bad_contract_version_raises(self) -> None:
        data = _valid()
        data["contract_version"] = "v1"
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("contract_version" in p for p in exc_info.value.problems)

    def test_bad_created_at_raises(self) -> None:
        data = _valid()
        data["created_at"] = "not-a-date"
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("created_at" in p for p in exc_info.value.problems)

    def test_valid_created_at_passes(self) -> None:
        data = _valid()
        data["created_at"] = "2026-01-15T09:30:00+00:00"
        validate_contract_dict(data)  # should not raise


class TestInvalidHashesAndEmbeddings:
    def test_bad_contract_hash_raises(self) -> None:
        data = _valid()
        data["contract_hash"] = "not-hex"
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("contract_hash" in p for p in exc_info.value.problems)

    def test_bad_anchor_embedding_raises(self) -> None:
        data = _valid()
        data["anchor_embedding"] = ["not", "floats"]
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("anchor_embedding" in p for p in exc_info.value.problems)

    def test_empty_anchor_embedding_raises(self) -> None:
        data = _valid()
        data["anchor_embedding"] = []
        with pytest.raises(InvalidContractError) as exc_info:
            validate_contract_dict(data)
        assert any("anchor_embedding" in p for p in exc_info.value.problems)


def test_error_message_lists_every_problem_not_just_first() -> None:
    data = {"semantic_anchors": []}  # missing agent_id, role_name, sector too
    with pytest.raises(InvalidContractError) as exc_info:
        validate_contract_dict(data)
    assert len(exc_info.value.problems) >= 4
    text = str(exc_info.value)
    assert "agent_id" in text and "role_name" in text and "sector" in text and "semantic_anchors" in text


def test_packaged_schema_copy_matches_repo_root_schema() -> None:
    """rmic_guard/schema/contract.schema.json (shipped inside the installed
    package) must stay byte-identical to schema/contract.schema.json (the
    repo-root copy referenced by README/docs) -- see the comment on
    [tool.setuptools.package-data] in pyproject.toml. This test is the
    automated half of that sync; it fails loudly if someone edits one copy
    and forgets the other."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    root_copy = repo_root / "schema" / "contract.schema.json"
    packaged_copy = repo_root / "rmic_guard" / "schema" / "contract.schema.json"
    assert root_copy.exists(), f"missing {root_copy}"
    assert packaged_copy.exists(), f"missing {packaged_copy} -- see pyproject.toml package-data"
    assert root_copy.read_text(encoding="utf-8") == packaged_copy.read_text(encoding="utf-8"), (
        "schema/contract.schema.json and rmic_guard/schema/contract.schema.json have drifted -- "
        "copy one over the other so pip-installed users and repo-clone users see the same schema."
    )
