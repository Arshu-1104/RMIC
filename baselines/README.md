# Baselines: Lakera Guard & NeMo Guardrails comparison

These two scripts run the exact same prompt set (`prompts/*.json`, all 4
roles from `contracts/`) through Lakera Guard and NeMo Guardrails, and write
results into the same `results/experiment_results.db` table your main
experiment uses — under `condition = "D_lakera_guard"` and
`condition = "E_nemo_guardrails"` respectively.

Because everything lands in one table with the same schema, `experiment/metrics.py`
and the `condition_summary` sheet in `export_run_summary_excel(...)` will show
RMIC-Guard next to both baselines automatically. No separate analysis needed.

## 1. Install dependencies

From the repo root:

```bash
pip install -r requirements.txt
```

This pulls in `nemoguardrails` and `langchain-openai` (added for these
baselines — `langchain-openai` is used because Groq's API is OpenAI-wire-
compatible) plus `httpx` (already required, used for the Lakera calls).

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

```
LAKERA_GUARD_API_KEY=lakera_guard_xxxxxxxxxxxxxxxxxxxx
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
GROQ_MODEL=llama-3.3-70b-versatile   # optional override
```

NeMo's `self_check_input` rail needs its own LLM to do the checking. This
uses Llama via Groq's free-tier, OpenAI-compatible API (matches the Groq
cost-management approach already explored elsewhere in the project).

Get a Groq key at https://console.groq.com/keys (free, no card required) —
sign in, click **API Keys**, **Create API Key**, copy it into `.env`.

**Fully local/offline alternative (no API key at all):**
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
```

Check the printed BLOCK/ALLOW decisions look sane before spending the full
budget.

## 5. Full run (same prompt count as your main experiment conditions)

```bash
python -m baselines.lakera_runner
python -m baselines.nemo_runner
```

Each prints its own `run_id` and writes CSV/JSON/XLSX exports to
`results/exports/`.

## 6. Compare against RMIC-Guard

Open the XLSX export's `condition_summary` sheet for any of the three
run_ids — it's grouped by `condition`, so `D_lakera_guard` and
`E_nemo_guardrails` rows sit right under `C_rmic_middleware`, `C1`, `C2`,
each with DSR / DDR / FPR already computed. If you want everything in one
export, run `export_run_summary_excel` against a run_id shared across all
five conditions — you'll need to pass the same `run_id` into all runners for
that (a `--run-id` flag can be added if you want a single merged export;
right now each baseline creates its own run_id for isolation).

## Known fairness caveats (state these in the write-up)

- Neither Lakera nor NeMo's self_check_input rail track state across a
  session the way RMIC-Guard's IDS trajectory metrics do — both baselines
  screen one input at a time. Expect them to do reasonably on `role_drift`
  (a single blunt override attempt) and worse on gradual `persona_drift`
  prompts that build up over conceptually multiple turns within one prompt.
- Lakera has no native "role contract" concept — we pass role_description /
  allowed_actions / forbidden_actions as a system message, which is the
  fairest available analogue but is closer to condition B (prompt-only)
  than condition C (structural enforcement).
- NeMo's flagging quality depends entirely on the checking LLM (here,
  Claude) correctly reasoning about the injected policy text — it's not a
  fixed, deterministic detector like RMIC-Guard's hard rules layer (C1).