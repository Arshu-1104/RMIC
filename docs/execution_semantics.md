# Execution semantics: what each decision does

This page states, for every decision `rmic-guard` can return, whether the tool runs. Each row
is pinned by a test in [`tests/test_execution_semantics.py`](../tests/test_execution_semantics.py).
Detection and prevention are not the same thing here: some decisions flag a call and still run
it. Evaluations should count executed calls, not "blocked or flagged" calls.

## Decisions of `guard.check()` / `session.check()`

| Decision | When | Tool runs? | `result.allowed` | `result.reason` | Audit log `decision` |
|---|---|---|---|---|---|
| `PASS` | No hard rule fired, and (semantic mode) IDS below the warn threshold with no velocity spike | **yes** | True | – | `PASS` |
| `PREEMPTIVE_WARN` | `semantic=True`: IDS below warn, but it rose more than `drift_velocity_threshold` since the previous call in the session | **yes** | True | `drift_velocity_exceeded` | `PREEMPTIVE_WARN` |
| `NEEDS_RECOVERY` | `semantic=True`: IDS between the warn and block thresholds | no | False | `ids_warn_threshold_reached` | `WARN` (see note) |
| `BLOCK` (IDS) | `semantic=True`: IDS at or above the block threshold | no | False | `ids_block_threshold_exceeded` | `BLOCK` |
| `BLOCK` (hard rule) | Forbidden or non-allowed tool, argument rule, parameter bound, session limit, prohibited data category, deny pattern (block) | no | False | e.g. `forbidden_tool`, `parameter_constraint:amount:above_max` | `BLOCK` |
| `NEEDS_CONFIRMATION` | A value above `confirm_above` | no, until `guard.confirm(id)` | False | `confirm_above:<param>` | `NEEDS_CONFIRMATION` |
| `CONFIRMED` | `guard.confirm(id)` of a pending call (single use, expires) | **yes**, exactly once | True | – | `CONFIRMED` |

- **`semantic=False` (the default)** returns only `PASS`, `BLOCK` (hard rule) and
  `NEEDS_CONFIRMATION`.
- **`semantic="monitor"`** returns the same three decisions as `semantic=False`. It adds the
  IDS and `result.ids_decision`, which is what `semantic=True` would have decided. The audit
  entry notes it as `monitor:would_<decision>`. In monitor mode a call the IDS would block
  still runs.
- **Hard-rule blocks come first.** A call that breaks a hard rule is blocked with the same
  reason in every mode, whatever the IDS says. So for identical inputs, semantic scoring can
  only add blocks; it never removes one (`test_full_mode_preserves_every_hard_rule_block`).
- **`guard.run()`** plans with an LLM, then enforces as above. On `NEEDS_RECOVERY` it re-plans
  with re-anchoring messages, up to `max_recovery` times. If the last plan is still not
  allowed, it returns `BLOCK` with reason `recovery_failed:...` and the tool does not run.
- **Note on naming:** the audit log records `NEEDS_RECOVERY` as `WARN`. This is a naming
  inconsistency, kept as is so existing logs remain comparable.

## What "every tool call is checked" means, and its limits

- **What is guaranteed.** Tools registered with a `Guard` run only through the enforcement
  engine. `ToolRegistry.execute()` refuses any call without the engine's per-process approval
  token: the result is `execution_not_approved_by_enforcement_engine` and the function is not
  called. Every `check()`, including blocked ones, appends one Ed25519-signed, hash-chained
  audit entry, so `guard.verify_log()` can show that each decision was recorded.
- **What isn't.** `rmic-guard` is a library. It cannot stop application code from calling a
  tool function directly, or from giving an agent other tools that never pass through the
  `Guard`. Every call is checked only if the application routes all tool execution through
  `guard.check()` / `guard.run()`.
- **The IBM watsonx Orchestrate pilot is weaker on both counts** (`ibm_pilot/LIVE_DEPLOYMENT.md`).
  - The guard there is a tool the agent is *instructed* to call on every message. Whether it is
    called depends on the model following that instruction.
  - It is a standalone file with the contract's hard rules inlined, plus a keyword list in place
    of the IDS: the reason `identity_drift_phrase_detected` comes from that keyword list, not
    from this engine.
  - The pilot demonstrates the integration path, not mandatory enforcement.
