"""Generate the hard-rule backward-compatibility snapshot (run once, before the
argument_rules / confirm_above / deny_patterns extensions were added).

    python tests/fixtures/backcompat/make_snapshot.py

Records, for every turn of every prompts/v2 item and each of the 4 contracts
as they were in v0.3, the decision and reason that Guard(contract) (hard rules
only) returns when that turn is checked on its own. Also copies the v0.3
financial_agent contract, which v0.4 re-seals with new fields, so the test can
still load the old version. tests/test_hard_rule_extensions.py replays both.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT))
os.environ.pop("RMIC_CONFIG", None)

from rmic_guard import Guard, load_contract  # noqa: E402

CONTRACTS = ("financial_agent", "healthcare_research_agent", "legal_review_agent", "support_agent")


def main() -> None:
    shutil.copyfile(REPO_ROOT / "contracts" / "financial_agent.json", HERE / "financial_agent_v0_3.json")
    snapshot: dict[str, list[dict]] = {}
    for name in CONTRACTS:
        guard = Guard(load_contract(REPO_ROOT / "contracts" / f"{name}.json"))
        raw = json.loads((REPO_ROOT / "prompts" / "v2" / f"{name}.json").read_text(encoding="utf-8"))
        rows = []
        items = [{"id": "warmup", "turns": raw["warmup"]}] + raw["attacks"] + raw["legitimate"]
        for item in items:
            for k, t in enumerate(item["turns"]):
                r = guard.session(f"{item['id']}:{k}").check(
                    t["tool"], message=t["message"], data=tuple(t.get("data") or ()), arguments=t.get("args") or {}
                )
                rows.append({
                    "item": item["id"], "turn": k, "tool": t["tool"], "args": t.get("args") or {},
                    "data": t.get("data") or [], "message": t["message"],
                    "decision": r.decision, "reason": r.reason,
                })
        snapshot[name] = rows
    (HERE / "hard_rule_decisions_v0_3.json").write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print({n: len(v) for n, v in snapshot.items()})


if __name__ == "__main__":
    main()
