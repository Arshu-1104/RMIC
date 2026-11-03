# Matched ablation: results

Run once on 2026-10-26 21:23:32 at commit `9fcf902c39cab989b7e617e340278f0e394bceea` with rmic-guard 0.4.1; 15315 items.

Plan, fixed before the run: [PLAN.md](PLAN.md). The same tool calls, in the same sessions, under each mode. An item is **stopped** if any of its turns did not execute. Cells are k/n (rate, Wilson 95% interval).

## external set

| Mode | Attacks stopped | Legitimate stopped | Attacks: BLOCK / NEEDS_RECOVERY / NEEDS_CONFIRMATION turns |
|---|---|---|---|
| C1 hard_rules_only | 72/80 (90.0%, 81.5–94.8) | 56/65 (86.2%, 75.7–92.5) | 188 / 0 / 0 |
| C2 ids_only | 57/80 (71.2%, 60.5–80.0) | 48/65 (73.8%, 62.0–83.0) | 0 / 166 / 0 |
| C full | 72/80 (90.0%, 81.5–94.8) | 56/65 (86.2%, 75.7–92.5) | 188 / 5 / 0 |

- **Semantic pass adds (C vs C1):** 0/80 (0.0%, 0.0–4.6) attacks additionally stopped; 0/65 (0.0%, 0.0–5.6) legitimate items additionally stopped (false positives).
- **Hard-rule blocks kept in C:** items stopped in C1 but executed in C = 0 (expected 0).
- **C2 (IDS only), item max-IDS:** ROC AUC 0.484; at 0.0% legitimate FPR it stops 2.5% of attacks; at 4.6% FPR, 6.2%.

## generated set

| Mode | Attacks stopped | Legitimate stopped | Attacks: BLOCK / NEEDS_RECOVERY / NEEDS_CONFIRMATION turns |
|---|---|---|---|
| C1 hard_rules_only | 37/45 (82.2%, 68.7–90.7) | 0/42 (0.0%, 0.0–8.4) | 37 / 0 / 0 |
| C2 ids_only | 21/45 (46.7%, 32.9–60.9) | 9/42 (21.4%, 11.7–35.9) | 0 / 23 / 0 |
| C full | 37/45 (82.2%, 68.7–90.7) | 9/42 (21.4%, 11.7–35.9) | 37 / 4 / 0 |

- **Semantic pass adds (C vs C1):** 0/45 (0.0%, 0.0–7.9) attacks additionally stopped; 9/42 (21.4%, 11.7–35.9) legitimate items additionally stopped (false positives).
- **Hard-rule blocks kept in C:** items stopped in C1 but executed in C = 0 (expected 0).
- **C2 (IDS only), item max-IDS:** ROC AUC 0.588; at 0.0% legitimate FPR it stops 2.2% of attacks; at 4.8% FPR, 8.9%.

## real data set

| Mode | Attacks stopped | Legitimate stopped | Attacks: BLOCK / NEEDS_RECOVERY / NEEDS_CONFIRMATION turns |
|---|---|---|---|
| C1 hard_rules_only | 0/2000 (0.0%, 0.0–0.2) | 95/13083 (0.7%, 0.6–0.9) | 0 / 0 / 0 |
| C2 ids_only | 5/2000 (0.2%, 0.1–0.6) | 7/13083 (0.1%, 0.0–0.1) | 0 / 5 / 0 |
| C full | 5/2000 (0.2%, 0.1–0.6) | 102/13083 (0.8%, 0.6–0.9) | 0 / 5 / 0 |

- **Semantic pass adds (C vs C1):** 5/2000 (0.2%, 0.1–0.6) attacks additionally stopped; 7/13083 (0.1%, 0.0–0.1) legitimate items additionally stopped (false positives).
- **Hard-rule blocks kept in C:** items stopped in C1 but executed in C = 0 (expected 0).
- **C2 (IDS only), item max-IDS:** ROC AUC 0.448; at 1.0% legitimate FPR it stops 2.1% of attacks; at 5.0% FPR, 7.2%.

## Caveat

Current IDS code (rmic-guard 0.4.1). The paper's runs used an IDS whose `semantic_grounding` also compared against forbidden topics (emptied on 22 Sep 2026), so this does not reproduce Table II; it measures the semantic pass as it is now, on identical inputs.
