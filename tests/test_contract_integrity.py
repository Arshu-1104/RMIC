from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.contract_loader import RMICContract, compute_contract_hash, load_contract, verify_contract
from core.exceptions import ContractIntegrityError, ContractNotSealedError


def _write_sealed_contract(tmp_path: Path) -> Path:
    out = tmp_path / "agent.json"
    RMICContract.create(
        agent_id="a", role_name="A", sector="s",
        semantic_anchors=["I do research."],
        require_embedding=False, save_to=out,
    )
    return out


class TestTamperDetection:
    def test_modifying_field_after_sealing_is_detected_on_load(self, tmp_path: Path) -> None:
        path = _write_sealed_contract(tmp_path)
        data = json.loads(path.read_text())
        data["allowed_actions"] = ["a_tool_that_was_never_approved"]  # tamper, hash now stale
        path.write_text(json.dumps(data))

        with pytest.raises(ContractIntegrityError):
            load_contract(path, verify_hash=True)

    def test_verify_contract_returns_false_on_tamper(self, tmp_path: Path) -> None:
        path = _write_sealed_contract(tmp_path)
        data = json.loads(path.read_text())
        data["role_name"] = "Something Else Entirely"
        path.write_text(json.dumps(data))

        assert verify_contract(path) is False

    def test_verify_contract_returns_true_for_untampered_contract(self, tmp_path: Path) -> None:
        path = _write_sealed_contract(tmp_path)
        assert verify_contract(path) is True

    def test_load_with_verify_hash_false_skips_check(self, tmp_path: Path) -> None:
        path = _write_sealed_contract(tmp_path)
        data = json.loads(path.read_text())
        data["role_name"] = "Tampered But Unverified"
        path.write_text(json.dumps(data))

        loaded = load_contract(path, verify_hash=False)  # should not raise
        assert loaded.role_name == "Tampered But Unverified"


class TestUnsealedContract:
    def test_load_unsealed_contract_with_verify_hash_raises(self, tmp_path: Path) -> None:
        unsealed = tmp_path / "unsealed.json"
        unsealed.write_text(json.dumps({
            "agent_id": "a", "role_name": "A", "sector": "s",
            "semantic_anchors": ["I do research."],
        }))
        with pytest.raises(ContractNotSealedError):
            load_contract(unsealed, verify_hash=True)

    def test_load_unsealed_contract_without_verify_hash_succeeds(self, tmp_path: Path) -> None:
        unsealed = tmp_path / "unsealed.json"
        unsealed.write_text(json.dumps({
            "agent_id": "a", "role_name": "A", "sector": "s",
            "semantic_anchors": ["I do research."],
        }))
        loaded = load_contract(unsealed, verify_hash=False)
        assert loaded.agent_id == "a"
        assert loaded.anchor_embedding == ()


class TestHashComputation:
    def test_hash_excludes_contract_hash_field_itself(self) -> None:
        base = {"agent_id": "a", "role_name": "A"}
        with_hash = dict(base, contract_hash="deadbeef")
        assert compute_contract_hash(base) == compute_contract_hash(with_hash)

    def test_hash_is_order_independent(self) -> None:
        a = {"agent_id": "a", "role_name": "A", "sector": "s"}
        b = {"sector": "s", "role_name": "A", "agent_id": "a"}
        assert compute_contract_hash(a) == compute_contract_hash(b)

    def test_hash_changes_when_content_changes(self) -> None:
        a = {"agent_id": "a", "role_name": "A"}
        b = {"agent_id": "a", "role_name": "B"}
        assert compute_contract_hash(a) != compute_contract_hash(b)
