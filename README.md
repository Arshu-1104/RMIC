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

If your platform can't run `fastembed`'s ONNX backend, install the PyTorch-based
fallback instead:

```bash
pip install "rmic-guard[torch]"
```

```python
from rmic_guard import load_contract, EnforcementEngine, ClaudeReasoning

contract = load_contract("contracts/financial_agent.json")
reasoning = ClaudeReasoning()
plan = reasoning.plan_tool_call(user_message, contract=contract, condition="C")

engine = EnforcementEngine(contract=contract, tools=my_tool_registry, ledger=None)
outcome = engine.evaluate_and_maybe_execute(
    plan, recent_ids=[], drift_type=None, execute_tool=True, enforcement_mode="full",
)
print(outcome.decision)  # "PASS" | "WARN" | "BLOCK" | "NEEDS_RECOVERY" | "PREEMPTIVE_WARN"
```

Groq (Llama) is supported as a drop-in alternative to Claude:

```python
from rmic_guard import GroqReasoning
reasoning = GroqReasoning(model_name="groq/llama-3.3-70b-versatile")
```

See [`PYPI_README.md`](PYPI_README.md) and [`examples/quickstart.py`](examples/quickstart.py)
for more. The sections below are for running the full research experiment
(benchmarking, dashboard, multi-model comparison) from a clone of this repo.

---

## Repository Structure

| Path | Contents |
|---|---|
| `core/` | The enforcement engine: contract loading (`contract_loader.py`), hard-rule + IDS enforcement (`enforcement_engine.py`), the IDS scoring wrapper (`ids_engine.py`) and its 7 signal implementations (`ids_metric.py`), local embeddings (`embedder.py`, `embedding_interface.py`), the signed audit ledger (`audit_ledger.py`), re-anchoring recovery (`recovery_engine.py`), tool dispatch (`tool_layer.py`), and reproducibility manifests (`integrity_manifest.py`). |
| `rmic_guard/` | The public SDK facade re-exported for `pip install rmic-guard` — no logic of its own; imports from `core/`. |
| `utils/` | Shared config loading (`config.py`) for `config.yaml`. |
| `contracts/` | Sealed JSON identity contracts for the 4 agent roles (`financial_agent`, `support_agent`, `healthcare_research_agent`, `legal_review_agent`) plus a blank `_template_universal.json`. |
| `prompts/` | The adversarial/legitimate prompt corpus, one JSON file per drift category (`role_drift`, `goal_drift`, `persona_drift`, `permission_drift`, `data_scope_drift`, `legitimate`). |
| `experiment/` | The research experiment runner (`runner.py`), metrics computation (`metrics.py`), SQLite results store with CSV/JSON/Excel export (`results_store.py`), statistical significance testing (`statistical_tests.py`), adversarial prompt generation (`adversarial.py`), and IDS threshold-calibration diagnostics (`ids_calibration_investigation/`). |
| `baselines/` | Head-to-head comparisons against Lakera Guard, NeMo Guardrails, and AgentDojo, plus diagnostic/calibration scripts — see [`baselines/README.md`](baselines/README.md). |
| `dashboard/` | FastAPI results dashboard (`app.py`) with a static frontend (`frontend/index.html`). |
| `ibm_pilot/` | IBM watsonx Orchestrate integration — see below. |
| `examples/` | `quickstart.py` — minimal end-to-end SDK usage. |
| `demo.py` | Root-level killer demo for Condition C (middleware-only enforcement). |
| `preflight_check.py` | No-API-call environment validation. |
| `seal_contracts.py` | Computes and writes the SHA-256 `contract_hash` (and embedding anchor, where possible) for each file in `contracts/`. |
| `paper_assets/` | Figures (ROC curves) supporting the write-up referenced below. |

---

## Prerequisites

- Python 3.10+ (3.11 recommended; developed and tested primarily on Windows)
- Anthropic API key (`sk-ant-...`) with credits

---

## Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

(On macOS/Linux, activate with `source .venv/bin/activate` instead.)

Create `.env` in the project root:

ANTHROPIC_API_KEY=your_key_here
ANTHROPIC_MODEL=claude-sonnet-4-6
GEMINI_API_KEY=your_key_here
GROQ_API_KEY=your_key_here


---

## Validate

```powershell
python preflight_check.py
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
ledger (`core/audit_ledger.py`), giving each entry a tamper-evident signature over its
timestamp, agent ID, IDS score, drift type, and decision.

Contracts are sealed before use: `seal_contracts.py` computes a SHA-256 hash over each
contract's fields (and an embedding anchor, when an embedding backend is available) and
writes it back into the contract file as `contract_hash`. `load_contract(..., verify_hash=True)`
(the default) checks this hash at load time; pass `verify_hash=False` to skip it during
local experimentation.

On a WARN-level IDS score, `core/recovery_engine.py` generates a re-anchoring system
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
`requirements.txt` (it can't import this repo's local `core/` package), the
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
