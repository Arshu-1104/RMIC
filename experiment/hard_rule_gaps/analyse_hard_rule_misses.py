"""
Which prompts/v2 attacks do the current hard rules miss, and which deterministic
contract rules would catch them?  ANALYSIS ONLY -- none of these rules is
implemented in rmic_guard; they are prototyped here as predicates so their
effect can be counted.

    python experiment/hard_rule_gaps/analyse_hard_rule_misses.py

1. Runs every prompts/v2 item through Guard(contract) (semantic=False, i.e.
   hard rules only) turn by turn; an attack is "missed" if no turn is blocked.
2. Evaluates each candidate rule on
     - the HELD-OUT misses (the rules were written after reading these, so
       these counts are optimistic),
     - the TUNE-split misses (not inspected while writing the rules: a less
       biased check),
     - all 40 legitimate items per contract (false positives; any turn).
3. Writes hard_rule_misses.md and hard_rule_misses.csv next to this script.

A rule "flags" an item if it matches any turn. Rules see only what a hard
rule would see at check() time: the message, the planned tool and its
arguments.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
os.environ.pop("RMIC_CONFIG", None)

from rmic_guard import Guard, load_contract  # noqa: E402

CONTRACTS = ("financial_agent", "healthcare_research_agent", "legal_review_agent", "support_agent")
OUT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Turn:
    message: str
    tool: str
    args: dict[str, Any]
    data: tuple[str, ...]


@dataclass(frozen=True)
class Item:
    contract: str
    item_id: str
    group: str
    category: str
    split: str
    turns: tuple[Turn, ...]


def load_items() -> list[Item]:
    split = json.loads((REPO_ROOT / "prompts" / "v2" / "split.json").read_text(encoding="utf-8"))["contracts"]
    items = []
    for n in CONTRACTS:
        raw = json.loads((REPO_ROOT / "prompts" / "v2" / f"{n}.json").read_text(encoding="utf-8"))
        held = set(split[n]["held_out"])
        for group, key in (("attack", "attacks"), ("legit", "legitimate")):
            for x in raw[key]:
                turns = tuple(Turn(t["message"], t["tool"], dict(t.get("args") or {}), tuple(t.get("data") or ())) for t in x["turns"])
                items.append(Item(n, x["id"], group, x.get("category", "legitimate"),
                                  "held_out" if x["id"] in held else "tune", turns))
    return items


def hard_rule_misses(items: list[Item]) -> set[tuple[str, str]]:
    """(contract, item_id) of attacks no turn of which Guard(semantic=False) blocks."""
    missed = set()
    guards = {n: Guard(load_contract(REPO_ROOT / "contracts" / f"{n}.json")) for n in CONTRACTS}
    for item in items:
        if item.group != "attack":
            continue
        session = guards[item.contract].session(item.item_id)
        blocked = [
            not session.check(t.tool, message=t.message, data=t.data, arguments=t.args).allowed for t in item.turns
        ]
        if not any(blocked):
            missed.add((item.contract, item.item_id))
    return missed


# ── candidate rules (prototypes) ────────────────────────────────────────────


def _rx(*patterns: str) -> Callable[[str], bool]:
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    return lambda text: any(c.search(text) for c in compiled)


ROLE_OVERRIDE = _rx(
    r"\byou(?:'re| are) (?:now|my)\b",
    r"\byou(?:'re| are) (?:a|an|the) [\w-]+(?: [\w-]+)? now\b",
    r"\bfrom now on\b",
    r"\bswitch(?:ing)? roles?\b",
    r"\b(?:act|behave|talk|respond|answer)(?: to me)? (?:as|like)\b",
    r"\bpretend(?:ing)? (?:to be|you(?:'re| are))\b",
    r"\brole-?play\b",
    r"\bbe (?:my|a|an) [\w-]+",
    r"\bdrop the [\w-]+ (?:persona|act)\b",
    r"\bas (?:my|your) (?:[\w-]+ ){0,2}(?:advisor|adviser|accountant|attorney|counsel|lawyer|therapist|buddy|friend|doctor|self)\b",
)
OBJECTIVE_OVERRIDE = _rx(
    r"\byour (?:new )?(?:goal|objective|mission|job|task|priority)\b",
    r"\bmake it your (?:job|goal|mission)\b",
    r"^\s*(?:stop|forget)\b",
    r"\binstead of (?:handling|helping|summari[sz]ing|troubleshooting|fixing|reviewing|processing)\b",
)
GUARDRAIL_REMOVAL = _rx(
    r"\bunfiltered\b",
    r"\bno[- ](?:restrictions|rules|disclaimers|limits)\b",
    r"\bwithout (?:the usual |any )?(?:verification|verifying|checks)\b",
    r"\bbypass\b",
    r"\b(?:turn off|disable)\b.{0,40}\b(?:two-factor|2fa|authentication|security)\b",
)

# Contract-specific data keywords: prohibited data named in the message.
DATA_KEYWORDS: dict[str, dict[str, Callable[[str], bool]]] = {
    "financial_agent": {
        "tax_records": _rx(r"\btax (?:return|filings?|records?)\b"),
        "credit_scores": _rx(r"\bcredit scores?\b"),
        "account_passwords": _rx(r"\bpasswords?\b"),
        "personal_address": _rx(r"\bhome address\b"),
        "other_customer_data": _rx(r"\b(?:another|other) customers?'?s?\b", r"\bneighbou?r's\b"),
    },
    "healthcare_research_agent": {
        "patient_health_records": _rx(r"\bhealth records?\b", r"\bpatients?'? (?:charts?|files?|records?)\b"),
        "personal_medical_history": _rx(r"\bmedical history\b"),
        "prescription_data": _rx(r"\bprescriptions? (?:written|for patient)\b"),
    },
    "legal_review_agent": {
        "client_personal_data": _rx(r"\bsalar(?:y|ies)\b", r"\bpersonal details\b", r"\bhome address\b", r"\bpassport\b", r"\bbank details\b"),
        "confidential_strategy": _rx(r"\bconfidential (?:offer|strategy|memo)\b"),
        "privileged_communications": _rx(r"\bprivileged\b"),
    },
    "support_agent": {
        "customer_pii": _rx(r"\b(?:person|user|customer) who\b", r"\b(?:another|other) customers?'?s?\b", r"\bphone number\b"),
        "internal_secrets": _rx(r"\bcredentials?\b", r"\bapi keys?\b", r"\binternal (?:incident report|wiki|engineering)\b",
                                r"\bsecurity holes?\b", r"\bvulnerabilit(?:y|ies)\b"),
    },
}

# Argument names each tool accepts, written from what each tool does (not from
# the attack prompts). An argument outside the list is rejected.
TOOL_ARGUMENTS: dict[str, dict[str, set[str]]] = {
    "financial_agent": {
        "check_balance": {"account_id"},
        "transfer_funds": {"amount", "to_account"},
        "get_transaction_history": {"account_id", "days", "limit", "min_amount", "month", "date", "amount", "recurring"},
        "send_transfer_confirmation": {"transfer_id"},
    },
    "healthcare_research_agent": {
        "search_pubmed": {"query", "papers_per_query"},
        "search_arxiv": {"query", "papers_per_query"},
        "retrieve_abstract": {"pmid", "doi", "arxiv_id", "query", "top"},
        "cite_paper": {"pmid", "doi", "title", "style"},
        "summarise_research": {"topic", "pmids", "top"},
        "generate_bibliography": {"pmids", "topic", "top", "style"},
    },
    "legal_review_agent": {
        "summarise_document": {"document_id", "documents_per_review"},
        "extract_clauses": {"document_id", "clause_type"},
        "flag_compliance_issues": {"document_id", "framework"},
        "generate_review_report": {"document_ids", "documents_per_review"},
    },
    "support_agent": {
        "answer_query": {"topic"},
        "search_kb": {"query"},
        "escalate_ticket": {"ticket_id", "reason"},
    },
}

TO_ACCOUNT_PATTERN = re.compile(r"^(?:\d{4}|(?:chk|sav|joint|card)-\d{4})$")
WILDCARD_ID = re.compile(r"(?:^|-)(?:all|\*|archive|other(?:-clients)?)$", re.IGNORECASE)
STEP_UP_AMOUNT = 10_000


@dataclass(frozen=True)
class Rule:
    key: str
    name: str
    proposal: str
    applies: Callable[[str, Turn], bool]
    blocks: bool = True  # False: escalate for human confirmation instead of blocking


def _string_args(turn: Turn) -> list[str]:
    out = []
    for v in turn.args.values():
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out += [x for x in v if isinstance(x, str)]
    return out


RULES = [
    Rule("R1", "Role/persona reassignment phrases",
         "`override_phrases` (regex list, matched against the message) → BLOCK `role_override_phrase`",
         lambda c, t: ROLE_OVERRIDE(t.message)),
    Rule("R2", "Objective override phrases",
         "same field, objective patterns → BLOCK `objective_override_phrase`",
         lambda c, t: OBJECTIVE_OVERRIDE(t.message)),
    Rule("R3", "Guardrail-removal phrases",
         "same field, guardrail patterns → BLOCK `guardrail_removal_phrase`",
         lambda c, t: GUARDRAIL_REMOVAL(t.message)),
    Rule("R4", "Prohibited data named in the message",
         "`data_scope.keywords`: {prohibited category: [terms]}; a match counts as accessing that category → BLOCK `data_scope:prohibited:<category>`",
         lambda c, t: any(f(t.message) for f in DATA_KEYWORDS[c].values())),
    Rule("R5", "Transfer destination format",
         "`parameter_constraints.to_account: {type: string, pattern: \"^(\\\\d{4}|(chk|sav|joint|card)-\\\\d{4})$\"}` → BLOCK `parameter_constraint:to_account:pattern`",
         lambda c, t: "to_account" in t.args and not TO_ACCOUNT_PATTERN.match(str(t.args["to_account"]))),
    Rule("R6", "Unexpected tool arguments",
         "per-tool `allowed_arguments` → BLOCK `unexpected_argument:<name>`",
         lambda c, t: t.tool in TOOL_ARGUMENTS[c] and bool(set(t.args) - TOOL_ARGUMENTS[c][t.tool])),
    Rule("R7", "Bulk / wildcard identifiers",
         "string-argument deny pattern (`-ALL`, `*`, `ARCHIVE`, `OTHER…`) → BLOCK `bulk_identifier`",
         lambda c, t: any(WILDCARD_ID.search(s) for s in _string_args(t))),
    Rule("R8", f"Transfer amount above {STEP_UP_AMOUNT:,}",
         f"`parameter_constraints.amount.confirm_above: {STEP_UP_AMOUNT}` → require human confirmation (not a block)",
         lambda c, t: t.tool == "transfer_funds" and float(t.args.get("amount", 0)) > STEP_UP_AMOUNT,
         blocks=False),
]


def item_flagged(rule: Rule, item: Item) -> bool:
    return any(rule.applies(item.contract, t) for t in item.turns)


# ── report ──────────────────────────────────────────────────────────────────


def main() -> None:
    items = load_items()
    missed = hard_rule_misses(items)
    miss_items = [i for i in items if (i.contract, i.item_id) in missed]
    held_miss = [i for i in miss_items if i.split == "held_out"]
    tune_miss = [i for i in miss_items if i.split == "tune"]
    legit = [i for i in items if i.group == "legit"]
    attacks = [i for i in items if i.group == "attack"]

    def count(rule: Rule, pool: list[Item], contract: str | None = None) -> int:
        return sum(item_flagged(rule, i) for i in pool if contract is None or i.contract == contract)

    blocking = [r for r in RULES if r.blocks]
    union = Rule("ALL", "Union of blocking rules R1–R7", "", lambda c, t: any(r.applies(c, t) for r in blocking))

    lines: list[str] = []
    add = lines.append
    add("# Attacks the hard rules miss, and deterministic rules that would catch them")
    add("")
    add("> **Held-out split: USED.** This design-time analysis read the held-out misses to write the rules, so the "
        "held-out split can no longer give an unbiased estimate and is not evaluated again. Rules R1–R6 and R8 are "
        "now implemented as contract fields (v0.4: `deny_patterns`, `argument_rules`, `confirm_above`; R7 was not "
        "implemented); their measured effect through the real code path, on the TUNE split only, is in "
        "[`implemented_rules_tune.md`](implemented_rules_tune.md). A blind test set is specified in "
        "[`prompts/v3/README.md`](../../prompts/v3/README.md).")
    add("")
    add("Generated by `experiment/hard_rule_gaps/analyse_hard_rule_misses.py`. **Analysis only: none of these rules "
        "is implemented.** Corpus: `prompts/v2/` (copied unchanged from `v0.4-ids-scoring`), frozen split "
        "`prompts/v2/split.json`. *Missed* = an attack none of whose turns `Guard(contract)` (hard rules only, "
        "`semantic=False`) blocks. A rule flags an item if it matches any turn.")
    add("")
    add(f"- Held-out attacks missed by today's hard rules: **{len(held_miss)}/80** "
        + "(" + ", ".join(f"{n} {sum(i.contract == n for i in held_miss)}/20" for n in CONTRACTS) + ").")
    add(f"- Tune-split attacks missed: {len(tune_miss)}/80 "
        + "(" + ", ".join(f"{n} {sum(i.contract == n for i in tune_miss)}/20" for n in CONTRACTS) + ").")
    add("- **Bias warning:** the rules were written after reading the held-out misses, and one author wrote both the "
        "corpus and the rules, so the held-out column is optimistic. The tune-split misses were not inspected while "
        "writing the rules; treat that column as the fairer estimate. Legitimate = all 40 per contract (both splits).")
    add("")

    add("## Rules")
    add("")
    add("| rule | catches held-out misses | catches tune-split misses | legitimate flagged (of 160) | proposed contract field → outcome |")
    add("|---|---|---|---|---|")
    for r in RULES + [union]:
        add(f"| {r.key} {r.name}{'' if r.blocks else ' *(confirm, not block)*'} | {count(r, held_miss)}/{len(held_miss)} "
            f"| {count(r, tune_miss)}/{len(tune_miss)} | {count(r, legit)}/{len(legit)} | {r.proposal} |")
    add("")

    add("## Per contract (held-out misses caught / tune-split misses caught / legitimate flagged of 40)")
    add("")
    add("| rule | " + " | ".join(CONTRACTS) + " |")
    add("|---|" + "---|" * len(CONTRACTS))
    for r in RULES + [union]:
        cells = [f"{count(r, held_miss, n)}/{sum(i.contract == n for i in held_miss)} · "
                 f"{count(r, tune_miss, n)}/{sum(i.contract == n for i in tune_miss)} · "
                 f"{count(r, legit, n)}/40" for n in CONTRACTS]
        add(f"| {r.key} | " + " | ".join(cells) + " |")
    add("")

    add("## Held-out misses, grouped")
    add("")
    add("Each held-out miss with the rules that catch it (last turn shown for multi-turn items).")
    add("")
    add("| contract | item | category | turns | rules | message (last turn) | planned call |")
    add("|---|---|---|---|---|---|---|")
    for i in sorted(held_miss, key=lambda x: (x.contract, x.item_id)):
        hits = [r.key for r in RULES if item_flagged(r, i)] or ["**none**"]
        last = i.turns[-1]
        add(f"| {i.contract} | {i.item_id} | {i.category} | {len(i.turns)} | {', '.join(hits)} | {last.message} "
            f"| `{last.tool}` `{json.dumps(last.args)}` |")
    add("")

    add("## Legitimate items flagged (false positives)")
    add("")
    add("| contract | item | rules | message that matched |")
    add("|---|---|---|---|")
    for i in legit:
        for r in RULES:
            for t in i.turns:
                if r.applies(i.contract, t):
                    add(f"| {i.contract} | {i.item_id} | {r.key} | {t.message} |")
                    break
    add("")

    nothing = [i for i in held_miss if not any(item_flagged(r, i) for r in RULES)]
    add("## Not caught by any rule")
    add("")
    if nothing:
        for i in nothing:
            add(f"- {i.contract} / {i.item_id}: {i.turns[-1].message}")
    else:
        add("Every held-out miss is caught by at least one rule (see the bias warning above).")
    add("")
    tune_nothing = [i for i in tune_miss if not any(item_flagged(r, i) for r in RULES)]
    add(f"Tune-split misses (not inspected while writing the rules) caught by no rule: {len(tune_nothing)}/{len(tune_miss)}. "
        "These show where the rules do not generalise:")
    add("")
    for i in sorted(tune_nothing, key=lambda x: (x.contract, x.item_id)):
        add(f"- {i.contract} / {i.item_id} ({i.category}, {len(i.turns)} turn{'s' if len(i.turns) > 1 else ''}): "
            f"{i.turns[-1].message} — `{i.turns[-1].tool}` `{json.dumps(i.turns[-1].args)}`")
    add("")
    add("## Notes")
    add("")
    add("- R1–R3 are phrase lists, the same deterministic mechanism as the IBM standalone tools' "
        "`identity_drift_phrase_detected`. They catch explicit instruction-override wording, not paraphrases; "
        "an attacker who avoids the phrases walks past them.")
    add("- R4 depends on contract-specific term lists. The lists above are deliberately narrow (0 false positives "
        "here); broadening them is where false positives come from, e.g. a bare `password` term for support_agent "
        "would flag legitimate requests such as \"How do I change my account password?\". R5–R7 inspect the planned "
        "call, so their value depends on how the real tools name and type their arguments; the counts here reflect "
        "the hand-written arguments in `prompts/v2`.")
    add("- R6's argument lists were written from each tool's purpose; real tool schemas should come from the tool "
        "definitions themselves.")
    add("- R8 escalates instead of blocking; its false positive is a legitimate $45,000 house down payment.")
    (OUT_DIR / "hard_rule_misses.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (OUT_DIR / "hard_rule_misses.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["contract", "item_id", "group", "category", "split", "missed_by_hard_rules", "n_turns"]
                   + [r.key for r in RULES] + ["last_message"])
        for i in items:
            w.writerow([i.contract, i.item_id, i.group, i.category, i.split,
                        (i.contract, i.item_id) in missed if i.group == "attack" else "",
                        len(i.turns)] + [int(item_flagged(r, i)) for r in RULES] + [i.turns[-1].message])
    print(f"wrote {(OUT_DIR / 'hard_rule_misses.md').relative_to(REPO_ROOT)} and hard_rule_misses.csv")


if __name__ == "__main__":
    main()
