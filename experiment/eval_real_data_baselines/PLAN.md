# Baselines on the same public real-world data: plan (pre-registered)

This plan is committed before any detector is run on the datasets. Each detector runs **once**
with its default settings, and nothing is tuned. The question: on the same Gandalf attacks and
Banking77 queries as [`../eval_real_data/`](../eval_real_data/PLAN.md), how do existing
prompt-injection detectors compare with rmic-guard?

Before this plan, the only contact with either detector was a setup check on two invented
sentences (not dataset text): one ProtectAI inference and one Lakera API call, to confirm the
model loads and the key works.

## Detectors

| Detector | What it is | Version | Licence / access |
|---|---|---|---|
| **ProtectAI deberta-v3-base-prompt-injection-v2** | Open-source text classifier (SAFE / INJECTION), run locally with ONNX Runtime | Hugging Face revision `90c9989b1a342275dd0d1a95aad283c04e075671`, `onnx/model.onnx` (SHA-256 `f0ea7f23…228c`), `onnx/tokenizer.json` (`752fe5f0…ff2f`), `onnx/config.json` (`30937430…23f8`) | Apache-2.0 |
| **Lakera Guard** | Commercial API, `POST https://api.lakera.ai/v2/guard` | API v2, the project policy attached to the key in `.env` (the same key as the paper's Condition D) | Commercial |

- **Meta Prompt Guard** (86M, and Llama Prompt Guard 2) is gated behind a manual licence request,
  so it was not run.
- **NeMo Guardrails self-check** needs one LLM call per text (about 14,000), so it was not run.

## How each is called

- **ProtectAI:**
  - **Input:** the text alone, tokenized with the model's tokenizer and truncated to 512 tokens.
  - **Decision:** `INJECTION` if it is the argmax class; this is the model card's default
    pipeline behaviour, with no threshold tuning.
  - **Score:** the INJECTION probability, used for the ROC AUC.
- **Lakera Guard:**
  - **Input:** `{"messages": [{"role": "system", "content": <role context>}, {"role": "user",
    "content": <text>}], "breakdown": true}`, where the role context is built exactly as
    `baselines/lakera_runner.py` builds it, from `financial_agent_hardened`.
  - **Primary decision:** `flagged`, which is what the paper's Condition D used.
  - **Secondary decision:** the `prompt_attack` detector alone, from the breakdown.
  - **Calls:** 4 at a time, with a 30 s timeout and up to 3 retries with backoff on network
    errors or HTTP 429/5xx. An item that still fails is recorded as an error and excluded from
    the rates, and the number of errors is reported.

## Items

- **ProtectAI:** all 1,000 Gandalf prompts and all 13,083 Banking77 queries.
- **Lakera Guard:** all 1,000 Gandalf prompts and the 3,080 queries of **Banking77's official
  test split**. This caps the run at about 4,100 API calls; the split was fixed here, before
  any result.
- **rmic-guard:** condition (b) of `../eval_real_data/` (hard rules plus deny patterns, the
  strongest rule-based condition). It is taken from the committed `results.csv`, not re-run.
  - A Gandalf prompt counts as blocked if its check with `check_balance` is `BLOCK`. The
    `transfer_funds` check gives identical decisions, because deny patterns read only the
    message.
  - A Banking77 query counts as blocked if its check is `BLOCK`.

## Metrics (k/n with a Wilson 95% interval)

- **Rates, for each detector and for rmic-guard (b) on the same items:**
  - attacks flagged, for all 1,000 prompts and for the test split (112);
  - Banking77 false positives, on all queries and on the test split.
- **Paired comparison against rmic-guard (b) on the same items:**
  - discordant counts (the detector flags and rmic doesn't, and the reverse) and the McNemar
    exact p;
  - the difference in rates, with a 95% Wilson interval for each rate.
- **Combination:** rmic-guard (b) **or** the detector (flag if either flags), to show whether
  they catch different things.
- **Score-based, ProtectAI only:** ROC AUC, and the attack rate at ≤1% and ≤5% Banking77
  false-positive rate.
- **Latency per call:** median and p95. ProtectAI runs on CPU on this machine; Lakera includes
  the network round trip.

## Fixed caveats

- **Training-data overlap.** Gandalf is Lakera's own game, and Lakera may have trained on these
  prompts. ProtectAI's training data is not verified against Gandalf or Banking77. Either would
  favour the detector.
- **Different jobs.** The detectors read text only. rmic-guard checks tools and arguments, which
  are always legitimate here by design. This compares detecting injection wording, not
  enforcing tool permissions.
- **Banking77's collection method is undocumented,** so these are public banking queries, not
  real customer traffic.
- **Data sharing.** Sending the texts to Lakera shares public dataset text with a third party.
