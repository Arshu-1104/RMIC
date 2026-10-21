# tests/

The SDK test suite: `pytest tests/` (offline; a deterministic fake embedding backend is installed in `conftest.py`).

`fixtures/backcompat/` holds the v0.3 hard-rule decision snapshot and the original
`financial_agent` contract that the backward-compatibility tests compare against.
The IBM pilot's tests live in `ibm_pilot/test_rmic_guard.py`.
