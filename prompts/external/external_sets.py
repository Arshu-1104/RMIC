"""Load the external evaluation sets, filling in the AgentHarm prompts the repository does not ship.

The committed prompts/external/<contract>.json files keep every AgentHarm item's ID, label and
tool mapping, but each AgentHarm turn's message is a placeholder (see WITHHELD). The prompts are
downloaded by scripts/fetch_agentharm.py into data/agentharm/ and filled back in here, giving
the frozen files byte for byte (validate_sets.py --check verifies their SHA-256).

    from external_sets import load_external
    doc = load_external("financial_agent")      # full set; needs scripts/fetch_agentharm.py first
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
AGENTHARM_DIR = REPO / "data" / "agentharm"
WITHHELD = "[withheld: AgentHarm prompt {source_id}; run scripts/fetch_agentharm.py]"


class AgentHarmMissing(RuntimeError):
    pass


def dumps(doc: dict) -> str:
    """The exact bytes of the frozen files: build_external_set.py wrote them with
    Path.write_text on Windows, so lines end in CRLF (JSON escapes newlines in strings)."""
    return (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").replace("\n", "\r\n")


def _items(doc: dict):
    for section in ("attacks", "legitimate"):
        yield from doc.get(section) or []


def redact(doc: dict) -> dict:
    out = copy.deepcopy(doc)
    for item in _items(out):
        if item.get("source") == "agentharm":
            for turn in item["turns"]:
                turn["message"] = WITHHELD.format(source_id=item["source_id"])
    return out


def _prompts(agentharm_dir: Path) -> dict[str, str]:
    prompts = {}
    for fname in ("harmful_behaviors_test_public.json", "benign_behaviors_test_public.json"):
        path = agentharm_dir / "benchmark" / fname
        if not path.exists():
            raise AgentHarmMissing(f"{path} not found: run `python scripts/fetch_agentharm.py` first")
        for b in json.loads(path.read_text(encoding="utf-8"))["behaviors"]:
            prompts[f"{fname}:{b['id']}"] = b["prompt"]
    return prompts


def hydrate(doc: dict, agentharm_dir: Path = AGENTHARM_DIR) -> dict:
    if not any(i.get("source") == "agentharm" for i in _items(doc)):
        return doc
    prompts = _prompts(agentharm_dir)
    out = copy.deepcopy(doc)
    for item in _items(out):
        if item.get("source") == "agentharm":
            for turn in item["turns"]:
                turn["message"] = prompts[item["source_id"]]
    return out


def load_external(contract: str, agentharm_dir: Path = AGENTHARM_DIR) -> dict:
    doc = json.loads((HERE / f"{contract}.json").read_text(encoding="utf-8"))
    return hydrate(doc, agentharm_dir)
