# scripts/

Repository maintenance and demo scripts; run them from the repository root.

| Script | What it does |
|---|---|
| `preflight_check.py` | No-API-call environment check (Python, keys, sealed contracts, embedding model, `results/`). |
| `demo.py` | Condition C demo: middleware-only enforcement on the healthcare contract (needs an API key). |
| `seal_contracts.py` | Re-seals contracts. Refuses the four frozen research contracts unless `--force` is passed. |
