"""In-memory sealing is deterministic; Guard warns about unsealed contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from rmic_guard import Guard, RMICGuardWarning, load_contract, seal_contract_file

REPO = Path(__file__).resolve().parents[1]

UNSEALED = {
    "agent_id": "stable-bot",
    "role_name": "Stable Bot",
    "sector": "general",
    "semantic_anchors": ["I answer questions about the product.", "I never touch billing."],
    "allowed_actions": ["answer"],
}

# Run in fresh interpreters. The embedding backend is deterministic across
# processes (unlike the conftest one, which uses the per-process salted hash()).
_CHILD = r"""
import hashlib, json, sys, warnings
import numpy as np
from rmic_guard import Guard, set_embedding_backend

def embed(texts):
    out = np.zeros((len(texts), 32), dtype=np.float32)
    for i, t in enumerate(texts):
        for j in range(max(1, len(t) - 2)):
            out[i, hashlib.sha256(t[j:j + 3].encode()).digest()[0] % 32] += 1.0
    return out

set_embedding_backend(embed)
warnings.simplefilter("ignore")
path = sys.argv[1]
print(json.dumps({
    "path": Guard(path, semantic=True).contract.contract_hash,
    "path_again": Guard(path, semantic=True).contract.contract_hash,
    "hard_rules_only": Guard(path).contract.contract_hash,
}))
"""


def _write_unsealed(tmp_path: Path) -> Path:
    path = tmp_path / "stable_bot.json"
    path.write_text(json.dumps(UNSEALED), encoding="utf-8")
    return path


@pytest.mark.parametrize("semantic", [False, True])
def test_same_unsealed_contract_hashes_the_same_twice_in_one_process(tmp_path: Path, semantic: bool) -> None:
    path = _write_unsealed(tmp_path)
    hashes = {
        Guard(path, semantic=semantic).contract.contract_hash,
        Guard(path, semantic=semantic).contract.contract_hash,
        Guard(dict(UNSEALED), semantic=semantic).contract.contract_hash,
        load_contract(path, require_embedding=semantic).contract_hash,
    }
    assert len(hashes) == 1
    assert Guard(path, semantic=semantic).contract.created_at is None  # nothing stamped in memory


def test_same_unsealed_contract_hashes_the_same_in_two_processes(tmp_path: Path) -> None:
    path = _write_unsealed(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "RMIC_CONFIG"}
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    runs = []
    for seed in ("1", "2"):  # different hash() salts, to be sure nothing depends on them
        env["PYTHONHASHSEED"] = seed
        out = subprocess.run(
            [sys.executable, "-c", _CHILD, str(path)], env=env, cwd=REPO,
            capture_output=True, text=True, check=True, timeout=120,
        )
        runs.append(json.loads(out.stdout.strip().splitlines()[-1]))
    assert runs[0] == runs[1]
    assert runs[0]["path"] == runs[0]["path_again"]
    assert runs[0]["hard_rules_only"] != runs[0]["path"]  # the embedding is part of the hash


def test_created_at_is_stamped_only_when_writing_back(tmp_path: Path) -> None:
    path = _write_unsealed(tmp_path)
    assert seal_contract_file(path).created_at is None
    assert load_contract(path, require_embedding=False).created_at is None
    sealed = seal_contract_file(path, write_back=True)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert sealed.created_at and on_disk["created_at"] == sealed.created_at
    assert load_contract(path).contract_hash == sealed.contract_hash


def test_guard_warns_when_it_seals_in_memory(tmp_path: Path) -> None:
    path = _write_unsealed(tmp_path)
    with pytest.warns(RMICGuardWarning, match=r"not sealed.*rmic seal"):
        Guard(path)
    with pytest.warns(RMICGuardWarning, match=r"not sealed.*rmic seal"):
        Guard(dict(UNSEALED))


def test_guard_does_not_warn_for_sealed_contracts(tmp_path: Path) -> None:
    path = _write_unsealed(tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RMICGuardWarning)
        Guard(path, save_sealed=True)  # sealed and written back: nothing to warn about
        Guard(path)
        Guard(REPO / "contracts" / "financial_agent.json")
