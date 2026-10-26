# experiment/

Research code: the experiment runner and its analyses (needs API keys; not run in CI).

| Path | Contents |
|---|---|
| `runner.py`, `metrics.py`, `results_store.py`, `statistical_tests.py`, `tuning.py`, `adversarial.py` | The experiment over `prompts/*.json` and the four research contracts, its metrics, storage and statistics. |
| `ids_calibration_investigation/` | IDS threshold-calibration diagnostics and the post-22-Sep calibration report. |
| `hard_rule_gaps/` | Which `prompts/v2` attacks the hard rules miss, and the tune-split evaluation of the v0.4 rules. |
| `perf/` | IDS latency before/after the embedding cache. |
| `eval_v0.4/` | The single v0.4 evaluation on the frozen external and generated sets: plan, script, results and raw CSVs. |
| `matched_ablation/` | Pre-registered replay of identical tool calls (external, generated and public real-world sets) under hard_rules_only, ids_only and full mode: what the semantic pass adds, and whether full mode keeps every hard-rule block. |
| `eval_real_data/` | The pre-registered evaluation on public data (Lakera Gandalf attacks, Banking77 queries): plan, mapping, script, per-check CSV (row ids and text hashes only), report and chart. |

The IDS v2 experiment (`ids_v2/`) lives on the `v0.4-ids-scoring` branch.
