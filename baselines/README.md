# Baselines: Lakera Guard, NeMo Guardrails & AgentDojo comparison

These scripts run the exact same prompt set (`prompts/*.json`, all 4
roles from `contracts/`) through Lakera Guard, NeMo Guardrails, and
AgentDojo's local prompt-injection detector, writing results into the
same `results/experiment_results.db` table your main experiment uses —
under `condition = "D_lakera_guard"`, `condition = "E_nemo_guardrails"`,
and `condition = "F_agentdojo"` respectively.

Because everything lands in one table with the same schema, `experiment/metrics.py`
and the `condition_summary` sheet in `export_run_summary_excel(...)` will show
RMIC-Guard next to all three baselines automatically. No separate analysis needed.

## 1. Install dependencies

From the repo root:

```bash
pip install -r requirements.txt
```

This pulls in `nemoguardrails` and `langchain-openai` (added for the NeMo
baseline — `langchain-openai` is used because Groq's API is OpenAI-wire-
compatible) plus `httpx` (already required, used for the Lakera calls).

**AgentDojo is not in `requirements.txt`** — install it separately:

```bash
pip install agentdojo
```

It runs fully locally (no API key), pulling `protectai/deberta-v3-base-prompt-injection-v2`
via `TransformersBasedPIDetector` on first use.

## 2. Get a Lakera Guard API key

1. Go to https://platform.lakera.ai and sign up (free tier exists, no card
   needed for evaluation use).
2. Create a **project** — don't skip this. The account-level default policy
   is intentionally very strict and will over-flag; a project lets you pick
   a policy that's representative of real usage.
3. In the project settings, go to **API Keys** and generate a new key. It
   will look like `lakera_guard_...`.
4. Copy it — Lakera only shows the full key once.

## 3. Add both keys to `.env`

LAKERA_GUARD_API_KEY=lakera_guard_xxxxxxxxxxxxxxxxxxxx
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
GROQ_MODEL=llama-3.3-70b-versatile # optional override


NeMo's `self_check_input` rail needs its own LLM to do the checking. This
uses Llama via Groq's free-tier, OpenAI-compatible API (matches the Groq
cost-management approach already explored elsewhere in the project).

Get a Groq key at https://console.groq.com/keys (free, no card required) —
sign in, click **API Keys**, **Create API Key**, copy it into `.env`.

AgentDojo needs no API key at all — it's a local model.

**Fully local/offline alternative for NeMo (no API key at all):**
1. Install Ollama: https://ollama.com/download (Windows/Mac) or
   `curl -fsSL https://ollama.com/install.sh | sh` (Linux).
2. `ollama pull llama3`
3. `ollama serve` — leave this running (listens on `http://localhost:11434`).
4. Verify it's up: `curl http://localhost:11434/api/tags` should list `llama3`.
5. Set `NEMO_LLM_BACKEND=ollama` in `.env` (no `GROQ_API_KEY` needed in
   this mode). Rerun `python -m baselines.nemo_runner` — it'll create a new
   `run_id`, so any earlier Groq-based `E_nemo_guardrails` results stay put.

## 4. Test run first (cheap, fast, 3 prompts × 4 roles = 12 calls each)

```bash
python -m baselines.lakera_runner --test
python -m baselines.nemo_runner --test
python -m baselines.agentdojo_runner --test
```

Check the printed BLOCK/ALLOW decisions look sane before spending the full
budget (AgentDojo is free either way, but the test run is still useful to
confirm the local model loads correctly).

## 5. Full run (same prompt count as your main experiment conditions)

```bash
python -m baselines.lakera_runner
python -m baselines.nemo_runner
python -m baselines.agentdojo_runner
```

Each prints its own `run_id` and writes CSV/JSON/XLSX exports to
`results/exports/`.

## 6. Compare against RMIC-Guard

Open the XLSX export's `condition_summary` sheet for any of the four
run_ids — it's grouped by `condition`, so `D_lakera_guard`,
`E_nemo_guardrails`, and `F_agentdojo` rows sit right under
`C_rmic_middleware`, `C1`, `C2`, each with DSR / DDR / FPR already computed.
If you want everything in one export, run `export_run_summary_excel`
against a run_id shared across all runners for that (a `--run-id` flag can
be added if you want a single merged export; right now each baseline
creates its own run_id for isolation) — or use `baselines/compare_all.py`,
which queries the whole database, groups by `condition` regardless of
run_id, and prints/exports one merged comparison table across all six
conditions:

```bash
python -m baselines.compare_all
```

## 7. Calibration and diagnostic scripts

A few smaller scripts support threshold tuning and debugging, separate
from the three baseline comparisons above:

- `python -m baselines.calibrate_ids_threshold [--model MODEL] [--n N]` —
  runs a Groq-only sample of legitimate and adversarial prompts through
  condition C's raw IDS scoring (hard rules bypassed via
  `enforcement_mode="ids_only"`) to check whether `warn_threshold` in
  `config.yaml` is set sensibly against real score distributions.
- `python -m baselines.diagnose_fpr [--db-path PATH] [--condition NAME]`
  (default condition: `C_rmic_middleware`) — pulls example rows where
  `expected_drift = 0` (legitimate prompts) from a condition's most
  recent run, to inspect exactly what was scored/decided on benign input.
- `python -m baselines.diagnose_legitimate [--role NAME] [--n N]`
  (default role: `financial_agent`) — tests a handful of legitimate
  prompts directly against `B_prompt_contract` and `C_rmic_middleware`
  for one role, without touching the database or running a full experiment.

## Known fairness caveats (state these in the write-up)

- Neither Lakera, NeMo's `self_check_input` rail, nor AgentDojo's detector
  track state across a session the way RMIC-Guard's IDS trajectory metrics
  do — all three baselines screen one input at a time. Expect them to do
  reasonably on `role_drift` (a single blunt override attempt) and worse
  on gradual `persona_drift` prompts that build up over conceptually
  multiple turns within one prompt.
- Lakera has no native "role contract" concept — we pass role_description /
  allowed_actions / forbidden_actions as a system message, which is the
  fairest available analogue but is closer to condition B (prompt-only)
  than condition C (structural enforcement).
- NeMo's flagging quality depends entirely on the checking LLM (here,
  Claude) correctly reasoning about the injected policy text — it's not a
  fixed, deterministic detector like RMIC-Guard's hard rules layer (C1).
- AgentDojo's `TransformersBasedPIDetector` is a generic prompt-injection
  classifier with no awareness of any role contract at all — it's the
  closest thing to an "off-the-shelf, zero-configuration" baseline, useful
  as a lower bound rather than a like-for-like comparison.
