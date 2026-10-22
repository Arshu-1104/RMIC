# RMIC-Guard

[![PyPI version](https://img.shields.io/pypi/v/rmic-guard)](https://pypi.org/project/rmic-guard/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Role-Model Identity Contract Guard** — research framework proving that enforcement
position (external middleware vs. in-prompt self-policing) is the primary determinant
of role identity drift suppression in autonomous LLM agents.

---

## Install the SDK

If you just want to use RMIC-Guard's enforcement engine in your own project (not
run the research experiments in this repo), install it from PyPI:

```bash
pip install rmic-guard
```

This installs only core enforcement functionality (contracts, validation, hard-rule +
semantic-drift enforcement, tool registry, audit ledger) — no LLM provider SDKs. If your
platform can't run `fastembed`'s ONNX backend, install the PyTorch-based fallback instead:

```bash
pip install "rmic-guard[torch]"
```

To also plan tool calls with a real LLM (Claude and/or Groq), install the matching extra:

```bash
pip install "rmic-guard[anthropic]"   # Claude, via LiteLLM
pip install "rmic-guard[groq]"        # Groq/Llama, via LiteLLM
pip install "rmic-guard[llm]"         # both
```

### Quickstart — one object, one call

```python
from rmic_guard import Guard

guard = Guard("contracts/bank_bot.json")        # load + validate + seal + verify

@guard.tool
def transfer_funds(amount: float, to: str):
    return {"sent": amount, "to": to}

result = guard.check("transfer_funds", amount=500, to="4321", message="pay rent")
print(result.allowed, result.decision, result.reason, result.output)

# Let an LLM plan the call (pip install "rmic-guard[groq]"):
result = guard.run("Transfer $500 to 4321 for rent", llm="groq/llama-3.3-70b-versatile")
```

`Guard` seals an unsealed contract in memory (the file is only rewritten with
`save_sealed=True`), verifies a sealed one (`ContractIntegrityError` on tampering),
keeps per-session IDS / tool-call history for you (`guard.reset()`,
`guard.session("user-42")`), executes the tool only on `PASS` / `PREEMPTIVE_WARN`,
and on `NEEDS_RECOVERY` in `run()` re-plans once with re-anchoring instructions.
`Guard(..., audit_log="audit.jsonl")` writes every decision to an Ed25519-signed
log that `guard.verify_log()` checks (each line is hash-chained to the previous one, so
deleted or reordered lines are detected too).

> **Semantic mode is experimental and off by default.** `Guard` enforces the
> contract's hard rules (forbidden tools, parameter bounds, data scope) unless you pass
> `semantic=True`. On the current scoring, the semantic identity-drift score (IDS) does
> not separate attacks from legitimate requests: across the 4 bundled contracts, attacks
> score *lower* than legitimate prompts (ROC AUC 0.35–0.49) and no warn/block threshold
> catches more than 3 of 25 attacks while flagging at most 1 of 15 legitimate requests. See the
> [calibration report](experiment/ids_calibration_investigation/post_sep22_threshold_calibration.md). Enable it only for evaluation.
> To collect IDS data on real traffic without affecting any decision, use
> `semantic="monitor"`: the IDS is computed and written to `GuardResult` (`ids_score`,
> `ids_decision` = what `semantic=True` would have decided) and to the audit log, while the
> hard rules alone decide.

By default (`semantic=False`) no embedding model is loaded and nothing touches the
network. With `semantic=True`, the first use downloads the `BAAI/bge-small-en-v1.5`
embedding model once (cached afterwards), and `run()`'s `NEEDS_RECOVERY` re-planning
comes into play.

### Contract hard-rule extensions (v0.4)

Four optional contract fields tighten the hard rules (`session_limits` since 0.4.1). They are
validated when the contract is loaded (an invalid regex is rejected), covered by the contract
hash, and contracts without them behave exactly as before.

**`argument_rules`: what a tool's arguments may look like.** Use `allowed_args` only for tools
with a fixed schema (e.g. function calling): an LLM writing free-form JSON invents argument names,
and an allowlist would then block legitimate calls.

```json
"argument_rules": {
  "transfer_funds": {
    "allowed_args": ["amount", "to_account"],
    "patterns": {"to_account": "\\d{4}|(?:chk|sav)-\\d{4}"},
    "max_length": 64
  }
}
```

- An argument not in `allowed_args` → `BLOCK`, reason `argument_not_allowed:<tool>:<arg>`.
- A value that does not **full-match** its pattern → `BLOCK`, reason `argument_pattern:<tool>:<arg>`.
  Strings and numbers (by their decimal form) are matched; lists element by element; any other
  type, or a value longer than `max_length` (default 1024), fails. Regexes are limited to 500
  characters.

**`confirm_above`: a human confirms large values.** Inside `parameter_constraints`:

```json
"parameter_constraints": {"amount": {"min": 0.01, "max": 50000, "confirm_above": 10000, "type": "float"}}
```

```python
result = guard.check("transfer_funds", amount=20000, to_account="4321")
result.decision          # "NEEDS_CONFIRMATION": the tool has not run; result.allowed is False
result.reason            # "confirm_above:amount"
done = guard.confirm(result.confirmation_id)   # runs the tool exactly once -> decision "CONFIRMED"
guard.confirm(result.confirmation_id)          # raises ConfirmationNotFoundError: ids are single-use
```

Values above `max` are still blocked outright. Both the `NEEDS_CONFIRMATION` and the `CONFIRMED`
entries are written to the hash-chained audit log with the same `confirmation_id`. Pending
confirmations live in memory in the `Guard` that issued them, and they are limited in two ways:

- **Time to live:** a top-level contract field `"confirmation_ttl_seconds": 300` (covered by
  the hash) is a ceiling. `Guard(..., confirmation_ttl_seconds=60)` can shorten it, but a longer
  value is ignored with an `RMICGuardWarning`. If the contract doesn't set it, the `Guard`
  argument applies, or 600 s by default.
- **Count:** at most 100 pending by default (`Guard(..., max_pending_confirmations=...)`, a
  `Guard` setting only). Issuing one more evicts the oldest.

Apps can show and withdraw pending requests:

```python
for p in guard.pending_confirmations():   # oldest first; expired ones are not listed
    print(p.confirmation_id, p.tool_name, p.arguments, p.reason, p.created_at, p.expires_at)
guard.cancel(p.confirmation_id)            # the tool never runs; returns what was cancelled
```

`created_at` and `expires_at` are UTC datetimes. A cancellation is written to the audit log as
a `BLOCK` with `failure_reason` `confirmation_cancelled` and the same `confirmation_id`.

`guard.confirm()` of an id that is no longer pending raises `ConfirmationNotFoundError`, and
`error.reason` says why: `"expired"`, `"evicted"`, `"cancelled"`, or `"unknown"` (never issued
or already used). The tool does not run. An expired or evicted id's failed `confirm()` is
written to the audit log as a `BLOCK` with `failure_reason` `confirmation_expired` /
`confirmation_evicted` and the same `confirmation_id`. A cancelled id isn't logged again,
because its cancellation already was.

**`deny_patterns`: opt-in phrase heuristics on the user's message.**

```json
"deny_patterns": {
  "packs": ["role_reassignment", {"name": "objective_override", "action": "warn"}, "guardrail_removal"],
  "custom": [{"id": "crypto", "regex": "\\bcrypto\\b", "action": "block"}],
  "prohibited_terms": {"terms": ["tax return", "credit score"], "action": "block"}
}
```

Matches block with reason `deny_pattern:<pack>:<pattern_id>` (`custom` and `prohibited_terms` are
pack names too); `"action": "warn"` lets the call run and lists the match in `result.warnings`.
Patterns are matched against the end user's message only, never the model's output
(`Guard.run()` passes the user's message separately). `prohibited_terms` match whole words,
case-insensitively. Only the first 10,000 characters of the message are scanned
(`"max_scan_chars"` in `deny_patterns` changes this). A longer message is still scanned up
to that point, and the result carries the warning `deny_pattern_scan_truncated:10000` (in
`result.warnings` and the audit log), so text past the limit is never matched.

> **These are heuristics, and rewording evades them.** The packs catch explicit wording such as
> "from now on you're my accountant" or "your new goal is…". "Instead of support, …" or
> "as the company's lawyer, …" get through. On the `prompts/v2` tune split the three packs caught
> 20 of the 41 attacks the other hard rules miss, with 0 of 80 legitimate items flagged
> (prohibited terms alone caught 3). On the original `prompts/` corpus they match 12–14 of 25
> attacks per contract. Both estimates are optimistic, because the same person wrote the
> `prompts/v2` attacks and the patterns (see `experiment/hard_rule_gaps/implemented_rules_tune.md`).
> They are off in every bundled contract. Treat them as a cheap extra layer, not as protection.

**`session_limits`: a running total per session.** Splitting one large transfer into many
small ones gets past `max` and `confirm_above`, which look at one call at a time. A session
limit adds up one numeric argument over a `guard.session(...)`:

```json
"session_limits": {"transfer_funds": {"param": "amount", "max_total": 50000}}
```

```python
s = guard.session("user-42")
s.check("transfer_funds", amount=30000, to_account="4321")   # PASS
s.check("transfer_funds", amount=25000, to_account="4321")   # BLOCK session_limit:transfer_funds:amount
s.session_totals                                             # {"transfer_funds:amount": 30000.0}
guard.session("user-43").check("transfer_funds", amount=25000, to_account="4321")   # PASS: own total
```

- A call is blocked when the amounts of the session's earlier allowed calls plus its own exceed
  `max_total`. Blocked calls add nothing.
- A `NEEDS_CONFIRMATION` call counts when it is issued, so pending transfers can't be stacked.
  `guard.confirm()` doesn't add it again, and a cancelled or expired confirmation is not
  refunded.
- A value that is not a finite, non-negative number is blocked with
  `session_limit:<tool>:<param>:invalid_value`, since it could lower the total.
- Totals live in memory, one per session id. `session.reset()` clears them, and they don't
  survive a restart. Each session id must stand for one end user: a caller who can pick a fresh
  session id gets a fresh total.

`contracts/examples/financial_agent_hardened.json` (`load_example_contract("financial_agent_hardened")`)
is the research `financial_agent` contract plus:

- `confirm_above: 10000`;
- account-format `patterns` (no `allowed_args`) that reject IBAN-shaped values (since 0.4.1);
- `session_limits` with `max_total: 50000` on `transfer_funds` `amount`, the same as the
  per-transfer `max` (since 0.4.1).

A session therefore can't move more than one maximum transfer in total. That doesn't stop the
v0.4 evaluation's $30,000 split (3 × $10,000): a lower `max_total` would, at the cost of
blocking legitimate sessions above it. The value was not tuned on any evaluation set.

### Evaluation (v0.4)

One evaluation, run once and with no tuning, on an **external public set (primary)** and a
**model-generated, context-isolated set (secondary)**. Each attack and legitimate request was
checked with `guard.check()` and `semantic=False`, under three conditions:

- **(a)** the v0.3 hard rules (the research contracts);
- **(b)** (a) plus `argument_rules` and `confirm_above` (`financial_agent_hardened`; the other
  contracts define neither, so (b) = (a) there);
- **(c)** (b) plus the three deny-pattern packs.

Cells are k/n with a Wilson 95% interval. Full results, including every miss and every false
positive verbatim (AgentHarm prompts withheld, see below):
[`experiment/eval_v0.4/results.md`](experiment/eval_v0.4/results.md).

| Set | Items | Attacks blocked (a) / (b) / (c) | Legitimate blocked (a) / (b) / (c) |
|---|---|---|---|
| External (AgentDojo banking, InjecAgent, AgentHarm; 4 contracts) | 80 attacks, 65 legitimate | 72/80 (90%, 81–95) in all three | 56/65 (86%, 76–93) in all three |
| Generated (`legal_review_agent` only) | 45 attacks, 42 legitimate | 37/45 (82%, 69–91) / 37/45 / 40/45 (89%, 77–95) | 0/42 (0%, 0–8) in all three |

How to read it:

- **On the external set, the contracts' tool lists did all the work.** Most items use dataset
  tools that are outside the contracts' allowed lists or map to forbidden tools. Those items are
  blocked in every condition, legitimate ones included, so the 86% says nothing about the v0.4
  extensions. The extensions changed no outcome there in either direction.
- **The 8 external attacks that got through** are all `financial_agent` transfers through the
  allowed `transfer_funds` tool: AgentDojo injection tasks sending money to an attacker's IBAN,
  and InjecAgent payment requests.
  - The account pattern accepts an IBAN as a valid account label (0.4.1 rejects IBANs in
    `financial_agent_hardened`; the results above are for 0.4.0).
  - The one $30,000 attack is split into transfers of at most $10,000, so `confirm_above: 10000`
    never fires.
- **Deny patterns are wording heuristics.** They added 3 blocks on the generated set and none on
  the external set, and caused no false positives on either.
- **Semantic mode is monitor-only.** In condition (d) (`semantic="monitor"`) the IDS did not
  separate attacks from legitimate requests (ROC AUC 0.48 external, 0.59 generated). Use
  `semantic="monitor"` to collect data, not to enforce.
- **Limits.**
  - The generated set exists for one contract only. Generation for the other three was stopped by
    a safety classifier and not retried.
  - Indirect injections were scored as if the attack text were the user's message, an upper
    bound for deny patterns.
  - A human-written blind set (`prompts/v3/README.md`) is still outstanding.
- **Datasets and licences.** AgentDojo and InjecAgent are MIT-licensed. AgentHarm
  (ai-safety-institute/AgentHarm) is MIT-licensed with an additional clause: use it only to
  improve the safety and security of AI systems, and for evaluation, not training. The
  repository does not redistribute AgentHarm's prompts. `prompts/external/` and `results.md`
  keep their behaviour IDs only, and `python scripts/fetch_agentharm.py` downloads the pinned
  revision into the git-ignored `data/agentharm/`. After that, `validate_sets.py --check` and
  `run_eval.py --verify` rebuild and check the full set. Attribution and licence texts:
  [`prompts/external/README.md`](prompts/external/README.md).

### Sealing

A sealed contract carries `contract_hash`, a SHA-256 over the canonical JSON of every other
field: the rules, the thresholds, `created_at` and, when present, `anchor_embedding` (the
averaged embedding of the `semantic_anchors`, used by semantic mode). Loading a sealed
contract recomputes the hash and raises `ContractIntegrityError` if it differs. Loading never
re-embeds, so a sealed file verifies the same way on every machine.

**Because the hash covers `anchor_embedding`, sealing is not reproducible across machines.**
The embedding comes from the local `fastembed` model. A different fastembed or onnxruntime
version, or a different CPU, can change the vector in its last digits, and any change gives a
different hash. Re-sealing the unchanged `financial_agent` contract on another setup changed
its embedding by up to 5.7e-5 per dimension, and so changed its hash. Two people sealing the
same unsealed file will usually get different hashes.

- **Seal once and distribute the sealed file.** `rmic seal contract.json` (or
  `Guard(path, save_sealed=True)`) writes `anchor_embedding` and `contract_hash` into the
  file. Commit that file and load it everywhere.
- **Don't re-seal an unchanged contract.** Re-sealing can change its hash and embedding, and
  with them every IDS score. When you change a field, re-seal once and redistribute.
- **In-memory auto-seal hashes are machine-specific.** `Guard("unsealed.json")` and
  `Guard({...})` seal in memory and emit an `RMICGuardWarning` pointing to `rmic seal`. The
  in-memory seal doesn't add `created_at` (only sealing that writes the file does). So loading
  the same unsealed contract again, in the same or another process, gives the same hash as long
  as the embedding is the same. With `semantic=True` or `"monitor"` the embedding, and with it
  the hash in `GuardResult` and the audit log, depends on the machine and fastembed version.
  Don't compare such hashes across machines. Seal the file if audit logs need one stable hash.
- With `semantic=False` an auto-sealed contract has no `anchor_embedding`, so its hash depends
  only on the JSON.
- Already-sealed contracts are unaffected: their `created_at` and hash are stored in the file.

Run `python examples/quickstart.py` for a fully offline PASS/BLOCK walkthrough, or see
`examples/basic_enforcement.py`, `examples/contract_creation.py`, and
`examples/identity_drift.py` for parameter constraints, data scope, the advanced
contract API, and semantic drift scoring respectively.

### Advanced / low-level API

`Guard` is built on these classes, which remain fully supported:

```python
from rmic_guard import ClaudeReasoning, EnforcementEngine, PlannedToolCall, load_contract

contract = load_contract("contracts/financial_agent.json")  # verifies contract_hash by default
reasoning = ClaudeReasoning()
plan = reasoning.plan_tool_call(user_message, contract=contract, condition="C")

engine = EnforcementEngine(contract=contract, tools=my_tool_registry, ledger=None)
outcome = engine.evaluate_and_maybe_execute(
    plan, recent_ids=[], drift_type=None, execute_tool=True, enforcement_mode="full",
)
print(outcome.decision)

# Without an LLM, build the plan yourself:
plan = PlannedToolCall(tool_name="web_search", arguments={"query": "hello"}, raw_text="hello")
```

Groq (Llama) is supported as a drop-in alternative to Claude:

```python
from rmic_guard import GroqReasoning
reasoning = GroqReasoning(model_name="groq/llama-3.3-70b-versatile")
```

### CLI

```bash
rmic init research-agent        # scaffold a new agent project (sealed contract + quickstart)
rmic validate contract.json     # check a contract against the schema, no sealing
rmic seal contract.json         # compute anchor_embedding + contract_hash, write back to the file
rmic verify contract.json       # check a sealed contract's hash is still intact
```

### Contract validation errors

Invalid contracts raise `InvalidContractError` listing every problem found (not just the
first), instead of a bare `KeyError`/`TypeError`:

```text
Invalid RMIC contract (RMICContract.create(...)):
  - role_name: missing required field (expected a non-empty string)
  - semantic_anchors: must contain at least one sentence
  - ids_warn_threshold must be <= ids_block_threshold (got warn=0.9, block=0.1)

See schema/contract.schema.json for the full contract schema.
```

The full contract schema is documented in [`schema/contract.schema.json`](schema/contract.schema.json).

See [`PYPI_README.md`](PYPI_README.md) for more. The sections below are for running the
full research experiment (benchmarking, dashboard, multi-model comparison) from a clone
of this repo.

---

## Repository Structure

| Path | Contents |
|---|---|
| `rmic_guard/` | The SDK shipped as `pip install rmic-guard`. `guard.py` is the high-level `Guard` API; `__init__.py` is the public import surface (LLM reasoning backends load lazily so they don't force a `litellm` install); `cli.py` implements the `rmic` command-line tool. `examples/` and `schema/` are the bundled copies of the research contracts (plus `financial_agent_hardened`) and of the JSON Schema. |
| `rmic_guard/_core/` | The enforcement engine (private; import from `rmic_guard` instead): contract loading (`contract_loader.py`), explicit pre-validation (`validation.py`), the SDK exception hierarchy (`exceptions.py`), litellm-free tool-call planning data model (`planning.py`), hard-rule + IDS enforcement (`enforcement_engine.py`), the IDS scoring wrapper (`ids_engine.py`) and its 7 signal implementations (`ids_metric.py`), local embeddings with a pluggable backend (`embedder.py`, `embedding_interface.py`), the signed audit ledger (`audit_ledger.py`), re-anchoring recovery (`recovery_engine.py`), tool dispatch (`tool_layer.py`), LLM reasoning backends (`reasoning_layer.py`), and reproducibility manifests (`integrity_manifest.py`). |
| `schema/` | `contract.schema.json` — the formal JSON Schema for the contract format, referenced by `rmic_guard/_core/validation.py`'s error messages (an identical copy ships in `rmic_guard/schema/`). |
| `rmic_guard/_utils/` | Config loading (`config.py`). The SDK reads a config file only when named explicitly via `RMIC_CONFIG`; the research scripts set it to this repo's `config.yaml`. |
| `contracts/` | Sealed JSON identity contracts for the 4 agent roles (`financial_agent`, `support_agent`, `healthcare_research_agent`, `legal_review_agent`); `examples/` holds `financial_agent_hardened.json` and `template.json`, a minimal contract to start from (see [`contracts/README.md`](contracts/README.md)). |
| `prompts/` | The v1 adversarial/legitimate prompt corpus used by the experiment, one JSON file per drift category (`role_drift`, `goal_drift`, `persona_drift`, `permission_drift`, `data_scope_drift`, `legitimate`); `v2/` is the per-contract corpus with a frozen tune/held-out split (held-out already used), `v3/` the brief for a future blind test set plus its model-generated secondary set (`v3/generated/`); `external/` the v0.4 external evaluation set built from public datasets. |
| `experiment/` | The research experiment runner (`runner.py`), metrics computation (`metrics.py`), SQLite results store with CSV/JSON/Excel export (`results_store.py`), statistical significance testing (`statistical_tests.py`), adversarial prompt generation (`adversarial.py`), IDS threshold-calibration diagnostics (`ids_calibration_investigation/`), the hard-rule gap analysis and evaluation of the v0.4 rules (`hard_rule_gaps/`), IDS latency measurements (`perf/`), and the v0.4 evaluation (`eval_v0.4/`). |
| `baselines/` | Head-to-head comparisons against Lakera Guard, NeMo Guardrails, and AgentDojo, plus diagnostic/calibration scripts — see [`baselines/README.md`](baselines/README.md). |
| `dashboard/` | FastAPI results dashboard (`app.py`) with a static frontend (`frontend/index.html`). |
| `ibm_pilot/` | IBM watsonx Orchestrate integration (adapter, standalone Orchestrate tools, agent YAMLs, `demo.py`, `run_single.py`, tests) — see below. |
| `examples/` | `quickstart.py` (offline `Guard` PASS/BLOCK), `basic_enforcement.py` (parameter/data-scope rules), `contract_creation.py` (beginner vs. advanced contract API), `identity_drift.py` (semantic IDS scoring). |
| `tests/` | `pytest` suite covering the `Guard` API, contract creation/validation/integrity/sealing, enforcement decisions and hard-rule extensions, audit-log verification, tool registry, IDS scoring, the CLI and `scripts/`; `fixtures/backcompat/` holds the v0.3 decision snapshot — `pytest tests/`. |
| `scripts/` | `demo.py` (killer demo for Condition C, middleware-only enforcement), `preflight_check.py` (no-API-call environment validation), `seal_contracts.py` (re-seals contracts; refuses the frozen research contracts unless `--force`). |
| `paper_assets/` | Figures (ROC curves) supporting the write-up referenced below. |

---

## Prerequisites

- Python 3.10–3.13 (3.11 recommended; developed and tested primarily on Windows).
  3.14 is not yet supported — `fastembed`'s pinned `onnxruntime` releases don't have
  verified Windows wheels for 3.14 at time of writing.
- Anthropic API key (`sk-ant-...`) with credits

---

## Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

(On macOS/Linux, activate with `source .venv/bin/activate` instead.)

The research scripts (`experiment/`, `baselines/`, `scripts/`,
`ibm_pilot/`) point the SDK at this repo's `config.yaml` by setting `RMIC_CONFIG`
themselves; set it explicitly to use a different config file.

Create `.env` in the project root:

ANTHROPIC_API_KEY=your_key_here
ANTHROPIC_MODEL=claude-sonnet-4-6
GEMINI_API_KEY=your_key_here
GROQ_API_KEY=your_key_here


---

## Validate

```powershell
python scripts/preflight_check.py
```

Runs 7 no-network checks (Python version, `.env`/provider keys, core modules import,
sealed contracts, local embedding model availability, `results/` directory, provider
SDK availability) and prints a `Checks passed: N / total` summary. Exits non-zero if
anything fails — fix the reported errors before running the experiment.

---

## Run Experiment

**Test run first** (cheap — 3 prompts × 4 roles × 4 conditions per model):

```powershell
python -m experiment.runner --test
```

**Restrict to specific models** — recommended: Groq only, since it's free/cheap
and avoids spending Anthropic credits:

```powershell
python -m experiment.runner --models groq/llama-3.3-70b-versatile,groq/llama-3.1-8b-instant
```

**Single model:**

```powershell
python -m experiment.runner --model groq/llama-3.3-70b-versatile
```

**All 4 configured models** (2 Anthropic + 2 Groq — spends Anthropic credits):

```powershell
python -m experiment.runner --multi-model
```

**Full run** inserts 40 prompts × 4 roles × 4 conditions × (number of models
selected) rows — e.g. 1,280 rows for a 2-model Groq-only run.

Run multiple times for statistical variance if comparing conditions closely.

---

## Statistical Report

```powershell
python -m experiment.statistical_tests
```

Requires 2+ full runs. Report saved to `results/statistical_report.txt`.

---

## Dashboard

```powershell
python -m uvicorn dashboard.app:app --reload --port 8001
```

Open `http://127.0.0.1:8001` — use the run selector to switch between runs.

The frontend (`dashboard/frontend/index.html`) is served from `/`, backed by JSON
APIs: `/api/overview`, `/api/ids-timeline`, `/api/stats`, `/api/provider-comparison`,
`/api/model-comparison`, `/api/runs-comparison`, and `/api/runs`/`/api/models` for
populating the run/model selectors.

---

## Experimental Design

**4 Roles:** `financial_agent`, `support_agent`, `healthcare_research_agent`, `legal_review_agent`

**4 Conditions:**

| Condition | Description |
|---|---|
| `B_prompt_contract` | Contract given in the system prompt only — LLM self-polices, no external enforcement |
| `C1_hard_rules_only` | Ablation — hard rules only (tool/parameter/data-scope checks), no IDS |
| `C2_ids_only` | Ablation — semantic IDS (embedding-based drift score) only, no hard rules |
| `C_rmic_middleware` | Full middleware — hard rules + IDS combined |

**40 prompts per role per condition** (adversarial: role/goal/persona/permission/data-scope
drift attempts, plus legitimate/benign controls).

---

## Results

The original RMIC-Guard experiment — 4 LLMs (claude-sonnet-4-6, claude-haiku-4-5,
llama-3.3-70b-versatile, llama-3.1-8b-instant), 4 agent roles, 5,212 API calls across two full
runs — is written up in:

> **"Role Model Identity Contract Enforcement as a Structural Determinant of Identity
> Drift Suppression in Autonomous LLM Agents"** — Sahana B, Charithra H S, Arshitha S,
> Chandrakala, Neethu B Krishna, Soumya Prasada, Bhanupriya P, Aryaman Tiwary —
> submitted to *International Journal of Electrical and Computer Engineering (IJECE)*.

**Headline finding:** external middleware enforcement (Condition C) reached DSR 0.952–
1.000 across all four models, while the best prompt-only condition (B) reached only DSR
0.391 (weakest model: 0.020) — a result that holds regardless of model architecture or
capability tier (χ²(3) = 847.3, p < 0.0001; Cohen's d = 1.84 for Base IDS, C vs. B).

**Ablation:** hard rules alone (C1) suppress drift (DSR ≈ 1.000) but at a steep false-positive
cost (FPR 0.62–0.67). Semantic IDS alone (C2) cannot issue terminal blocks without a hard-
rule violation to anchor on. The dual-pass design — both passes together — is what makes
the system both safe and operationally viable.

**Open problems the paper identifies**, both still relevant to this repo: per-role ROC
calibration to bring FPR down without sacrificing DSR, and latency optimization (batched
embedding calls, centroid caching) for interactive use cases. The threshold-calibration
work is ongoing in [`experiment/ids_calibration_investigation/`](experiment/ids_calibration_investigation)
(ROC analysis, embedding-model comparisons, signal diagnostics).

> **Reproducibility note:** the code has received bug fixes since this data was collected —
> most notably, tool-name matching now tolerates case/formatting variance, condition
> C's model no longer silently invents tool names outside the contract vocabulary, and
> genuine model refusals are no longer overwritten by a forced JSON-correction retry.
> Re-running the experiment on the current code may shift individual numbers slightly
> from the paper's Table 1, though the core structural finding — external enforcement
> beats prompt-only self-policing — is the more robust result and isn't expected to
> change.

Later work extended this with head-to-head comparisons against off-the-shelf tools —
Lakera Guard, NeMo Guardrails, and AgentDojo's local prompt-injection detector — see
[`baselines/README.md`](baselines/README.md).

---

## IDS Metrics (7 Independent Signals)

| Metric | Description |
|---|---|
| Base IDS | 0.4 × RoleDistance + 0.4 × SemanticGrounding + 0.2 × TrajectoryCurvature |
| Mahalanobis | Covariance-aware distance in 384-dim embedding space |
| KL Divergence | Asymmetric early-warning divergence signal |
| Jensen–Shannon | Primary enforcement metric — symmetric, bounded [0, 1] |
| Wasserstein | Geometry-aware Earth Mover's Distance |
| Hellinger | Tail-sensitive, bounded [0, 1] |
| Tool Frequency | Behavioral pattern drift across session window |

All 7 computed independently. Never blended into a single number at enforcement time —
only Base IDS feeds the WARN/BLOCK decision; the rest are diagnostic signals recorded per
call.

---

## Key Metrics

| Metric | Definition |
|---|---|
| DSR | Drift Suppression Rate = blocked / expected_drift |
| DDR | Drift Detection Rate = detected / expected_drift |
| FPR | False Positive Rate = false_detections / legitimate |

`experiment/metrics.py` also reports precision, recall, and a separate aggregate
"IDS" quality score (0.45·DDR + 0.45·DSR + 0.10·(1−FPR)) used for run-level summaries —
distinct from the per-call Base IDS drift score above.

---

## Audit Ledger & Contract Sealing

Every enforcement decision can be recorded to an append-only, Ed25519-signed JSONL
ledger (`rmic_guard/_core/audit_ledger.py`), giving each entry a tamper-evident signature over its
timestamp, agent ID, IDS score, drift type, and decision. Each line also stores the SHA-256 of
the previous line inside its signed payload, so `verify_file()` detects deleted, inserted and
reordered lines as well as edits (tail truncation needs an externally recorded
`AuditLedger.head_hash()`). The signing key persists across
restarts (`audit_key=` / `RMIC_AUDIT_KEY` / `<log>.key`), and the public key is written to
`<log>.pub` so `AuditLedger.verify_file(<log>)` can check the log later.

Contracts are sealed before use: `scripts/seal_contracts.py` computes a SHA-256 hash over each
contract's fields (and an embedding anchor, when an embedding backend is available) and
writes it back into the contract file as `contract_hash` (it refuses to rewrite the four frozen
research contracts unless `--force` is passed; `seal_contract_file(..., write_back=True)`;
since v0.3.0 `seal_contract_file()` alone seals in memory only). `load_contract(..., verify_hash=True)`
(the default) checks this hash at load time; pass `verify_hash=False` to skip it during
local experimentation. An unsealed file is sealed automatically on load (`auto_seal=True`,
the default), in memory only unless you also pass `write_back=True`. The hash covers
`anchor_embedding`, which differs between machines and fastembed versions: see
[Sealing](#sealing) before re-sealing a contract.

On a WARN-level IDS score, `rmic_guard/_core/recovery_engine.py` generates a re-anchoring system
message and user nudge derived from the contract's sealed `semantic_anchors`, giving the
model one retry before a hard BLOCK — this is what produces the `NEEDS_RECOVERY` /
`PREEMPTIVE_WARN` decisions in `EnforcementOutcome`.

---

## Exports

Each full run auto-exports to `results/exports/{run_id}.csv`, `{run_id}.json`, and a
summary `.xlsx` (via `experiment/results_store.py`). Row count scales with the run size
(prompts × roles × conditions × models); the current schema has 24 columns, including
role/condition/decision metadata and all 7 IDS signal scores per call.

---

## IBM watsonx Orchestrate Pilot

RMIC-Guard has been deployed and verified live inside a real IBM watsonx
Orchestrate instance for the **financial agent** role, proving the enforcement
model is portable to a third-party agent orchestration framework, not just
this repo's own pipeline. See [`ibm_pilot/LIVE_DEPLOYMENT.md`](ibm_pilot/LIVE_DEPLOYMENT.md)
for the architecture and live-verified results (4/4 test scenarios), and
[`ibm_pilot/README.md`](ibm_pilot/README.md) for the full pilot design.

Because Orchestrate's Python-tool sandbox only receives a single file plus a
`requirements.txt` (it can't import this repo's `rmic_guard` package), the
deployed tool is a self-contained adapter (`orchestrate_tool_standalone.py`)
that inlines the sealed contract's rules directly, with a keyword-based
stand-in for the semantic IDS scoring.

The same standalone pattern has also been implemented for the **legal review**
(`legal_guard_tool_standalone.py`, `rmic_legal_review_agent.yaml`) and
**healthcare research** (`orchestrate_tool_standalone_healthcare.py`,
`pubmed_search.py`, `rmic_healthcare_agent.yaml`) agent roles. These are not
yet documented as live-tested in an Orchestrate instance — only the financial
agent pilot has recorded live deployment results.

**Demo video:** [RMIC-Guard × IBM watsonx Orchestrate — Live Pilot Demo](https://youtu.be/xQer0t_11fo)

[![RMIC-Guard × watsonx Orchestrate Demo](https://img.youtube.com/vi/xQer0t_11fo/maxresdefault.jpg)](https://youtu.be/xQer0t_11fo)

---

## Contributing

Bug reports, questions, and pull requests are welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## Team Branches

| Branch | Scope |
|---|---|
| `charithra/core` | Core engine |
| `chandrakala/experiment` | Experiment pipeline |
| `arshitha/dashboard` | Dashboard |
| `neethu/contracts` | Contracts and prompts |
