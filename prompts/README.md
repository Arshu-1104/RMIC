# prompts/

Prompt corpora for the experiment and the hard-rule evaluations.

| Path | Contents |
|---|---|
| `*.json` | The v1 corpus used by `experiment/runner.py` and `baselines/`: one file per drift category plus `legitimate.json`. Frozen; its hash is part of each run's manifest. |
| `v2/` | Per-contract corpus (40 attacks + 40 legitimate each) with a frozen tune/held-out split in `split.json`. The held-out split has been used and must not be used for tuning again. |
| `v3/` | Instructions for a blind test set written by people who have not seen the rules (no human-written items yet). `v3/generated/` holds a model-generated, context-isolated, not human-blind secondary set (one contract). |
| `external/` | The v0.4 external evaluation set: items from AgentDojo, InjecAgent and AgentHarm, selected and mapped mechanically (see `external/SELECTION.md`), frozen by `external/SHA256SUMS`. |
