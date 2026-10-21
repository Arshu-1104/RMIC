"""Validate the v0.4 evaluation sets and write prompts/external/SHA256SUMS.

    python prompts/external/validate_sets.py          # validate and (re)write SHA256SUMS
    python prompts/external/validate_sets.py --check  # validate and verify against SHA256SUMS

Checks structure only (ids unique, labels/categories known, every turn has a message, a tool
and an object of args). Prints counts, never item text.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = ("financial_agent", "healthcare_research_agent", "legal_review_agent", "support_agent")
CATEGORIES = {"role_drift", "goal_drift", "persona_drift", "permission_drift", "data_scope_drift"}
SUMS = REPO / "prompts" / "external" / "SHA256SUMS"


def _check_turns(where: str, turns: object, problems: list[str]) -> None:
    if not isinstance(turns, list) or not turns:
        problems.append(f"{where}: turns must be a non-empty list")
        return
    for j, t in enumerate(turns):
        if not isinstance(t, dict) or not isinstance(t.get("message"), str) or not t["message"].strip():
            problems.append(f"{where}.turns[{j}]: missing message")
        elif not isinstance(t.get("tool"), str) or not t["tool"]:
            problems.append(f"{where}.turns[{j}]: missing tool")
        elif not isinstance(t.get("args", {}), dict):
            problems.append(f"{where}.turns[{j}]: args must be an object")


def _validate(path: Path, *, generated: bool, problems: list[str]) -> str:
    d = json.loads(path.read_text(encoding="utf-8"))
    if d.get("contract") not in CONTRACTS or d["contract"] != path.stem:
        problems.append(f"{path}: contract field must be {path.stem}")
    ids: set[str] = set()
    for section in ("attacks", "legitimate"):
        for i, item in enumerate(d.get(section) or []):
            where = f"{path.name}:{section}[{i}]"
            if item.get("id") in ids:
                problems.append(f"{where}: duplicate id {item.get('id')!r}")
            ids.add(item.get("id"))
            if generated and section == "attacks" and item.get("category") not in CATEGORIES:
                problems.append(f"{where}: unknown category")
            if not generated and item.get("label") != ("attack" if section == "attacks" else "legitimate"):
                problems.append(f"{where}: label does not match section")
            _check_turns(where, item.get("turns"), problems)
    if generated:
        for j, t in enumerate(d.get("warmup") or []):
            _check_turns(f"{path.name}:warmup[{j}]", [t], problems)
    return f"{path.relative_to(REPO).as_posix()}: attacks={len(d.get('attacks') or [])} legitimate={len(d.get('legitimate') or [])}"


def main() -> int:
    files = [(REPO / "prompts" / "external" / f"{c}.json", False) for c in CONTRACTS]
    files += [(p, True) for p in sorted((REPO / "prompts" / "v3" / "generated").glob("*.json"))]
    problems: list[str] = []
    for path, generated in files:
        print(_validate(path, generated=generated, problems=problems))
    if problems:
        print("\n".join(problems))
        return 1
    hashed = files + [(REPO / "prompts" / "external" / "raw" / "agentdojo_banking_v1.2.2.json", False)]
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(REPO).as_posix()}" for p, _ in hashed]
    if "--check" in sys.argv:
        ok = SUMS.read_text(encoding="utf-8").splitlines() == lines
        print("SHA256SUMS match" if ok else "SHA256SUMS MISMATCH")
        return 0 if ok else 1
    SUMS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {SUMS.relative_to(REPO).as_posix()} ({len(lines)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
