"""`rmic init` scaffolds a sealed contract whose quickstart runs without warnings."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rmic_guard import load_contract
from rmic_guard.cli import main

REPO = Path(__file__).resolve().parents[1]


def test_init_seals_the_scaffolded_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init", "research-agent"]) == 0
    contract_path = tmp_path / "research-agent" / "contracts" / "research-agent.json"
    data = json.loads(contract_path.read_text(encoding="utf-8"))
    assert data["contract_hash"] and data["created_at"] and "anchor_embedding" not in data
    assert load_contract(contract_path).contract_hash == data["contract_hash"]
    assert main(["verify", str(contract_path)]) == 0

    env = {k: v for k, v in os.environ.items() if k != "RMIC_CONFIG"}
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    run = subprocess.run(
        [sys.executable, "-W", "error::UserWarning", str(tmp_path / "research-agent" / "examples" / "quickstart.py")],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, run.stderr
    assert "decision=PASS" in run.stdout and "reason=forbidden_tool" in run.stdout
