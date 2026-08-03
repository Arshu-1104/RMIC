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

See [`PYPI_README.md`](PYPI_README.md) and [`examples/quickstart.py`](examples/quickstart.py)
for more. The sections below are for running the full research experiment
(benchmarking, dashboard, multi-model comparison) from a clone of this repo.

---

## Prerequisites

- Python 3.11 (Windows recommended)
- Anthropic API key (`sk-ant-...`) with credits

---

## Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `.env` in the project root:

```
ANTHROPIC_API_KEY=your_key_here
ANTHROPIC_MODEL=claude-sonnet-4-6
GEMINI_API_KEY=your_key_here
GROQ_API_KEY=your_key_here
```

---

## Validate

```powershell
python preflight_check.py
```

Expected: 6/6 checks pass.

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
embedding calls, centroid caching) for interactive use cases.

> **Reproducibility note:** the code has received bug fixes since this data was collected —
> most notably, tool-name matching now tolerates case/formatting variance, condition
> C's model no longer silently invents tool names outside the contract vocabulary, and
> genuine model refusals are no longer overwritten by a forced JSON-correction retry.
> Re-running the experiment on the current code may shift individual numbers slightly
> from the paper's Table 1, though the core structural finding — external enforcement
> beats prompt-only self-policing — is the more robust result and isn't expected to
> change.

Later work extended this with head-to-head comparisons against off-the-shelf tools —
Lakera Guard and NeMo Guardrails — see [`baselines/README.md`](baselines/README.md).

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

All 7 computed independently. Never blended.

---

## Key Metrics

| Metric | Definition |
|---|---|
| DSR | Drift Suppression Rate = blocked / expected_drift |
| DDR | Drift Detection Rate = detected / expected_drift |
| FPR | False Positive Rate = false_detections / legitimate |

---

## Exports

Each full run auto-exports to `results/exports/{run_id}.csv` (1,300 rows, 22 columns).

---

## Team Branches

| Branch | Scope |
|---|---|
| `charithra/core` | Core engine |
| `chandrakala/experiment` | Experiment pipeline |
| `arshitha/dashboard` | Dashboard |
| `neethu/contracts` | Contracts and prompts |
