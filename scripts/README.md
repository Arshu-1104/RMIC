# scripts/

Repository maintenance and demo scripts; run them from the repository root.

| Script | What it does |
|---|---|
| `preflight_check.py` | No-API-call environment check (Python, keys, sealed contracts, embedding model, `results/`). |
| `demo.py` | Condition C demo: middleware-only enforcement on the healthcare contract (needs an API key). |
| `fetch_real_eval_data.py` | Downloads Lakera `gandalf_ignore_instructions` (MIT) and Banking77 (CC BY 4.0) for `experiment/eval_real_data/`, from pinned revisions with SHA-256 checks, into the git-ignored `data/real_eval/`. |
| `fetch_agentharm.py` | Downloads the AgentHarm prompts of the v0.4 external evaluation set (pinned revision, SHA-256 checked) into the git-ignored `data/agentharm/`; the repository does not redistribute them. |
| `seal_contracts.py` | Re-seals contracts. Refuses the four frozen research contracts unless `--force` is passed. |
