from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.contract_loader import RMICContract, load_contract, seal_contract_file
from core.exceptions import InvalidContractError


def _anchors() -> list[str]:
    return [
        "I perform research and information gathering.",
        "I do not perform destructive or unauthorized actions.",
    ]


class TestBeginnerCreateAPI:
    def test_create_offline_no_embedding(self) -> None:
        contract = RMICContract.create(
            agent_id="research-agent",
            role_name="Research Agent",
            sector="research",
            semantic_anchors=_anchors(),
            allowed_actions=["web_search"],
            forbidden_actions=["delete_data"],
            require_embedding=False,
        )
        assert contract.agent_id == "research-agent"
        assert contract.allowed_actions == ("web_search",)
        assert contract.forbidden_actions == ("delete_data",)
        assert contract.anchor_embedding == ()
        assert len(contract.contract_hash) == 64  # sha256 hex digest

    def test_create_with_embedding(self) -> None:
        # Uses the deterministic backend installed by tests/conftest.py
        contract = RMICContract.create(
            agent_id="a",
            role_name="A",
            sector="s",
            semantic_anchors=_anchors(),
            require_embedding=True,
        )
        assert len(contract.anchor_embedding) > 0

    def test_create_persists_when_save_to_given(self, tmp_path: Path) -> None:
        out = tmp_path / "agent.json"
        RMICContract.create(
            agent_id="a", role_name="A", sector="s", semantic_anchors=_anchors(),
            require_embedding=False, save_to=out,
        )
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["agent_id"] == "a"
        assert "contract_hash" in data

    def test_create_rejects_invalid_inputs(self) -> None:
        with pytest.raises(InvalidContractError) as exc_info:
            RMICContract.create(
                agent_id="a", role_name="", sector="s", semantic_anchors=[],
                require_embedding=False,
            )
        problems = "\n".join(exc_info.value.problems)
        assert "role_name" in problems
        assert "semantic_anchors" in problems

    def test_defaults_match_config_thresholds(self) -> None:
        contract = RMICContract.create(
            agent_id="a", role_name="A", sector="s", semantic_anchors=_anchors(),
            require_embedding=False,
        )
        assert 0.0 <= contract.ids_warn_threshold <= 1.0
        assert 0.0 <= contract.ids_block_threshold <= 1.0
        assert contract.ids_warn_threshold <= contract.ids_block_threshold


class TestAdvancedAPI:
    def test_load_contract_roundtrip(self, tmp_path: Path) -> None:
        out = tmp_path / "agent.json"
        created = RMICContract.create(
            agent_id="a", role_name="A", sector="s", semantic_anchors=_anchors(),
            require_embedding=False, save_to=out,
        )
        loaded = load_contract(out, verify_hash=True)
        assert loaded.contract_hash == created.contract_hash
        assert loaded.agent_id == created.agent_id

    def test_seal_contract_file_writes_hash_and_embedding(self, tmp_path: Path) -> None:
        raw = tmp_path / "unsealed.json"
        raw.write_text(json.dumps({
            "agent_id": "a", "role_name": "A", "sector": "s",
            "semantic_anchors": _anchors(),
        }))
        sealed = seal_contract_file(raw)
        assert sealed.contract_hash
        assert len(sealed.anchor_embedding) > 0
        on_disk = json.loads(raw.read_text())
        assert on_disk["contract_hash"] == sealed.contract_hash

    def test_load_contract_missing_field_raises_invalid_contract_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"role_name": "A", "sector": "s"}))
        with pytest.raises(InvalidContractError) as exc_info:
            load_contract(bad, verify_hash=False)
        assert any("agent_id" in p for p in exc_info.value.problems)
        assert any("semantic_anchors" in p for p in exc_info.value.problems)

    def test_load_contract_bad_json_raises_invalid_contract_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        with pytest.raises(InvalidContractError):
            load_contract(bad, verify_hash=False)

    def test_to_dict_roundtrips_through_load_contract(self, tmp_path: Path) -> None:
        contract = RMICContract.create(
            agent_id="a", role_name="A", sector="s", semantic_anchors=_anchors(),
            allowed_actions=["t1"], require_embedding=False,
        )
        out = tmp_path / "roundtrip.json"
        out.write_text(json.dumps(contract.to_dict()))
        reloaded = load_contract(out, verify_hash=True)
        assert reloaded.allowed_actions == ("t1",)
        assert reloaded.contract_hash == contract.contract_hash
