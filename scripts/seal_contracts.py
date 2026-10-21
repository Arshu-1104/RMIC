"""Seal RMIC contracts with real embeddings when possible, else stdlib-only fallback.

    python scripts/seal_contracts.py [contract.json ...] [--force]

With no paths, targets the four research contracts in contracts/. Those are
frozen: the experiment, the paper and the IBM pilot depend on their exact
bytes, and re-sealing changes anchor_embedding and contract_hash (sealing is
not reproducible across machines or fastembed versions). They are therefore
refused unless --force is passed. Other contracts are sealed in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # repository root
sys.path.insert(0, str(ROOT))  # make the repository's rmic_guard importable

CONTRACT_RELPATHS = (
    "contracts/financial_agent.json",
    "contracts/support_agent.json",
    "contracts/healthcare_research_agent.json",
    "contracts/legal_review_agent.json",
)
FROZEN = frozenset((ROOT / rel).resolve() for rel in CONTRACT_RELPATHS)


def compute_contract_hash(data: dict) -> str:
    """SHA-256 over stable JSON of all fields except contract_hash (matches rmic_guard._core.contract_loader)."""
    payload = {k: v for k, v in sorted(data.items()) if k != "contract_hash"}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _embedding_backend_label() -> str:
    try:
        import fastembed  # noqa: F401

        return "fastembed"
    except ImportError:
        return "sentence-transformers"


def _seal_fallback(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError("contract file must contain a JSON object")

    data["anchor_embedding"] = []
    if data.get("created_at") in (None, ""):
        data["created_at"] = datetime.now(timezone.utc).isoformat()
    data["contract_hash"] = compute_contract_hash(data)

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    agent_id = str(data.get("agent_id", path.stem))
    h = data["contract_hash"]
    print(f"Sealed (fallback mode — no embedding): {agent_id}: {h[:16]}...")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="contracts to seal (default: the four research contracts)")
    parser.add_argument("--force", action="store_true", help="also rewrite the frozen research contracts")
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.paths] or [ROOT / rel for rel in CONTRACT_RELPATHS]
    refused = [p for p in paths if p.resolve() in FROZEN and not args.force]
    for p in refused:
        print(
            f"Refusing to rewrite frozen research contract {p.relative_to(ROOT) if p.is_absolute() else p}: "
            "its exact bytes are part of the experiment and the IBM pilot. Pass --force to re-seal it anyway.",
            file=sys.stderr,
        )
    paths = [p for p in paths if p not in refused]
    if not paths:
        return 1 if refused else 0
    be = _embedding_backend_label()

    try:
        from rmic_guard._core.contract_loader import seal_contract_file
    except ImportError:
        seal_contract_file = None

    for p in paths:
        if seal_contract_file is not None:
            try:
                sealed = seal_contract_file(p, write_back=True)
                print(
                    f"Sealed (real embeddings via {be}): {sealed.agent_id}: "
                    f"{sealed.contract_hash[:16]}..."
                )
            except (ImportError, OSError, ValueError, RuntimeError, Exception) as exc:
                print(f"Real sealing failed for {p.stem} ({exc}), using fallback...")
                _seal_fallback(p)
        else:
            print(f"contract_loader unavailable, using fallback for {p.stem}...")
            _seal_fallback(p)

    print(f"{len(paths)} contract(s) processed. Now run: python scripts/preflight_check.py")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())