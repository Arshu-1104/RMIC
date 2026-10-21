"""Repository scripts: scripts/seal_contracts.py never rewrites the frozen research contracts by default."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESEARCH = ("financial_agent", "healthcare_research_agent", "legal_review_agent", "support_agent")


def _digests() -> dict[str, str]:
    return {n: hashlib.sha256((REPO / "contracts" / f"{n}.json").read_bytes()).hexdigest() for n in RESEARCH}


def test_seal_contracts_refuses_frozen_research_contracts_without_force() -> None:
    before = _digests()
    env = {k: v for k, v in os.environ.items() if k != "RMIC_CONFIG"}
    for args in ([], [str(REPO / "contracts" / "support_agent.json")]):
        run = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "seal_contracts.py"), *args],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
        )
        assert run.returncode == 1, run.stdout + run.stderr
        assert "Refusing to rewrite frozen research contract" in run.stderr
        assert "--force" in run.stderr
    assert _digests() == before
