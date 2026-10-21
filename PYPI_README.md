# rmic-guard

Role-boundary preservation and identity-drift detection for autonomous LLM agents.

`rmic-guard` gives an agent a **contract** — an explicit statement of its role,
allowed/forbidden tools, and data-access scope — and enforces it at runtime
with two layers:

- **Hard rules**: exact-match checks on tool names, parameter bounds, and data scope.
- **IDS (Identity Drift Score)**: an embedding-based signal (role distance,
  semantic grounding, trajectory curvature) that flags gradual drift a
  hard-rule check alone would miss.

## Install

```bash
pip install rmic-guard
```

This installs core enforcement plus the local `fastembed` embedding backend —
no LLM provider SDKs. To also plan tool calls with a real LLM:

```bash
pip install "rmic-guard[anthropic]"   # Claude, via LiteLLM
pip install "rmic-guard[groq]"        # Groq/Llama, via LiteLLM
pip install "rmic-guard[llm]"         # both
```

If your platform can't run `fastembed`'s ONNX backend, install the
PyTorch-based fallback instead:

```bash
pip install "rmic-guard[torch]"
```

## Quickstart

```python
from rmic_guard import Guard

guard = Guard("contracts/bank_bot.json")        # load + validate + seal + verify

@guard.tool
def transfer_funds(amount: float, to: str):
    return {"sent": amount, "to": to}

result = guard.check("transfer_funds", amount=500, to="4321", message="pay rent")
print(result.allowed, result.decision, result.reason, result.output)
```

`Guard` loads the contract (a file path, a dict, or an `RMICContract`), seals
it in memory if it isn't sealed yet, and verifies the hash if it is
(`ContractIntegrityError` on tampering). `guard.check(...)` enforces one tool
call and runs your function **only** if it is allowed.

> **Semantic mode is experimental and off by default.** `Guard` enforces the
> contract's hard rules (forbidden tools, parameter bounds, data scope) unless you pass
> `semantic=True`. On the current scoring, the semantic identity-drift score (IDS) does
> not separate attacks from legitimate requests: across the 4 bundled contracts, attacks
> score *lower* than legitimate prompts (ROC AUC 0.35–0.49) and no warn/block threshold
> catches more than 3 of 25 attacks while flagging at most 1 of 15 legitimate requests. See the
> [calibration report](https://github.com/Arshu-1104/RMIC/blob/main/experiment/ids_calibration_investigation/post_sep22_threshold_calibration.md). Enable it only for evaluation.
> To collect IDS data on real traffic without affecting any decision, use
> `semantic="monitor"`: the IDS is computed and written to `GuardResult` (`ids_score`,
> `ids_decision` = what `semantic=True` would have decided) and to the audit log, while the
> hard rules alone decide.


| `GuardResult` field | Meaning |
|---|---|
| `allowed` | `True` for `PASS` / `PREEMPTIVE_WARN` |
| `decision` | `PASS`, `BLOCK`, `NEEDS_RECOVERY` or `PREEMPTIVE_WARN` |
| `reason` | hard-rule violation (`forbidden_tool`, `parameter_constraint:amount:above_max`, ...) or IDS reason |
| `ids_score` | Identity Drift Score (0 in hard-rules-only mode) |
| `output` | your tool's return value, or `None` if it didn't run |
| `recovery_attempted`, `contract_hash` | recovery flag and the contract that was enforced |

Pass the data categories a call touches with `data=["ssn"]`. Per-session IDS
and tool-call history is kept for you: `guard.reset()` clears it, and
`guard.session("user-42").check(...)` gives each conversation its own history.

### Fully offline: hard rules only

```python
guard = Guard({"agent_id": "bot", "role_name": "Bot", "sector": "demo",
               "semantic_anchors": ["I check balances."],
               "allowed_actions": ["check_balance"], "forbidden_actions": ["admin_login"]},
              semantic=False)   # the default; shown for clarity
guard.register("check_balance", lambda: {"balance": 100})
print(guard.check("check_balance"))   # allowed=True, decision=PASS
print(guard.check("admin_login"))     # allowed=False, decision=BLOCK, reason=forbidden_tool
```

`semantic=False` (the default) enforces forbidden tools, parameter bounds and
data scope with no embedding model and no network. With the experimental
`semantic=True`, **the first use downloads the `BAAI/bge-small-en-v1.5`
embedding model once** (then it's cached locally).

### Let an LLM plan the call

```bash
pip install "rmic-guard[groq]"   # or [anthropic]
```

```python
result = guard.run("Transfer $500 to 4321 for rent", llm="groq/llama-3.3-70b-versatile")
```

With `semantic=True` (experimental), if the plan lands in the IDS warn zone (`NEEDS_RECOVERY`), `run()` re-plans
once with re-anchoring instructions (`max_recovery=1`) and enforces again; if
it still isn't allowed, the result is blocked and the tool never runs.

### Signed audit log

```python
guard = Guard("contracts/bank_bot.json", audit_log="audit.jsonl")
...
guard.verify_log()   # False if any entry was edited, deleted, inserted or reordered
```

Every decision is appended to `audit.jsonl` with an Ed25519 signature, and
each line stores the SHA-256 of the line before it, so deleted or reordered
lines break the chain. (Cutting lines off the *end* leaves a shorter valid
chain: record `AuditLedger.head_hash("audit.jsonl")` elsewhere to detect that.) The
signing key comes from `audit_key=...`, else `RMIC_AUDIT_KEY`, else
`audit.jsonl.key` (created with 0600 permissions on first use). The public
key is written to `audit.jsonl.pub`, so `AuditLedger.verify_file("audit.jsonl")`
works after a restart or on another machine.

### Contract hard-rule extensions

Optional contract fields, validated at load and covered by the contract hash:

- `argument_rules`: per-tool `allowed_args` (for fixed-schema tools) and full-match `patterns`
  for argument values → `BLOCK argument_not_allowed:<tool>:<arg>` / `argument_pattern:<tool>:<arg>`.
- `confirm_above` in `parameter_constraints`: larger values return `NEEDS_CONFIRMATION`
  (tool not run); `guard.confirm(result.confirmation_id)` runs it exactly once and logs it.
- `deny_patterns` (opt-in): phrase packs `role_reassignment`, `objective_override`,
  `guardrail_removal`, your own regexes and `prohibited_terms`, matched against the user's
  message → `BLOCK deny_pattern:<pack>:<id>` or a warning. **These are heuristics: rewordings
  evade them.**

See the [README on GitHub](https://github.com/Arshu-1104/RMIC#contract-hard-rule-extensions-v04)
for examples, and `load_example_contract("financial_agent_hardened")` for a contract using them.

## Writing contracts in code

`RMICContract.create(...)` validates the contract, computes its semantic-anchor
embedding (unless `require_embedding=False`), hashes it, and seals it — all in
one call. Invalid contracts raise `InvalidContractError` listing every problem
found, not just the first:

```text
Invalid RMIC contract (RMICContract.create(...)):
  - role_name: missing required field (expected a non-empty string)
  - semantic_anchors: must contain at least one sentence
```

## Advanced / low-level API

`Guard` is a layer over these classes, which remain fully supported:

```python
from rmic_guard import (
    ClaudeReasoning, EnforcementEngine, PlannedToolCall, ToolRegistry, load_contract,
)

contract = load_contract("contracts/financial_agent.json")  # verifies contract_hash by default
reasoning = ClaudeReasoning()  # reads ANTHROPIC_API_KEY from the environment
plan = reasoning.plan_tool_call(
    "What's my current account balance?", contract=contract, condition="C",
)

engine = EnforcementEngine(contract=contract, tools=ToolRegistry(), ledger=None)
outcome = engine.evaluate_and_maybe_execute(
    plan,
    recent_ids=[],       # pass prior IDS scores for trajectory tracking across a session
    drift_type=None,
    execute_tool=True,
    enforcement_mode="full",  # "full" | "hard_rules_only" | "ids_only"
)
print(outcome.decision)  # "PASS" | "BLOCK" | "NEEDS_RECOVERY" | "PREEMPTIVE_WARN"
```

Groq (Llama) is supported as a drop-in alternative to Claude:

```python
from rmic_guard import GroqReasoning
reasoning = GroqReasoning(model_name="groq/llama-3.3-70b-versatile")
```

## Configuration

The SDK uses each contract's own `ids_warn_threshold` / `ids_block_threshold`.
It reads a YAML config file only when you name one explicitly, via the
`RMIC_CONFIG` environment variable; a `config.yaml` that happens to sit in
your working directory is ignored.

## CLI

```bash
rmic init research-agent        # scaffold a new agent project (contract + quickstart)
rmic validate contract.json     # check a contract against the schema, no sealing
rmic seal contract.json         # compute anchor_embedding + contract_hash, write back to the file
rmic verify contract.json       # check a sealed contract's hash is still intact
```

## Writing a contract

A contract is a JSON file describing the agent's role, its allowed and
forbidden tools, parameter constraints, and data-access scope. The full
schema ships inside the package at `rmic_guard/schema/contract.schema.json`,
and is also readable directly on GitHub:
https://github.com/Arshu-1104/RMIC/blob/main/schema/contract.schema.json

See `contracts/` in the [GitHub repo](https://github.com/Arshu-1104/RMIC)
for real examples across financial, support, healthcare-research, and
legal-review agent roles.

## Status

This is an early (0.3.x) release from an active research project on
role-boundary preservation in autonomous agents. APIs may change between
minor versions until 1.0. Issues and contributions welcome on
[GitHub](https://github.com/Arshu-1104/RMIC).

## License

MIT
