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

This installs only core enforcement functionality — no LLM provider SDKs. To also
plan tool calls with a real LLM:

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

## Quickstart — no LLM key, no network call

```python
from rmic_guard import RMICContract, ToolRegistry, EnforcementEngine
from core.planning import PlannedToolCall

contract = RMICContract.create(
    agent_id="research-agent",
    role_name="Research Agent",
    sector="research",
    role_description="Performs safe research tasks.",
    semantic_anchors=[
        "I perform research and information gathering.",
        "I do not perform destructive or unauthorized actions.",
    ],
    allowed_actions=["web_search"],
    forbidden_actions=["delete_data"],
    require_embedding=False,  # skip the semantic-drift model download for this demo
)

tools = ToolRegistry()
tools.register("web_search", lambda query: {"results": [f"Search results for: {query}"]})
tools.register("delete_data", lambda path: {"deleted": path})

engine = EnforcementEngine(contract=contract, tools=tools)

safe = engine.evaluate_and_maybe_execute(
    PlannedToolCall("web_search", {"query": "hello"}, "hello"),
    recent_ids=[], enforcement_mode="hard_rules_only",
)
print(safe.decision)  # PASS

blocked = engine.evaluate_and_maybe_execute(
    PlannedToolCall("delete_data", {"path": "/prod/db"}, "delete the prod db"),
    recent_ids=[], enforcement_mode="hard_rules_only",
)
print(blocked.decision)  # BLOCK
```

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

```python
from rmic_guard import load_contract, seal_contract_file, verify_contract, EnforcementEngine, ClaudeReasoning

contract = load_contract("contracts/financial_agent.json")  # verifies contract_hash by default
reasoning = ClaudeReasoning()  # reads ANTHROPIC_API_KEY from the environment
plan = reasoning.plan_tool_call(
    "What's my current account balance?", contract=contract, condition="C",
)

engine = EnforcementEngine(contract=contract, tools=my_tool_registry, ledger=None)
outcome = engine.evaluate_and_maybe_execute(
    plan,
    recent_ids=[],       # pass prior IDS scores for trajectory tracking across a session
    drift_type=None,
    execute_tool=True,
    enforcement_mode="full",  # "full" | "hard_rules_only" | "ids_only"
)
print(outcome.decision)  # "PASS" | "WARN" | "BLOCK" | "NEEDS_RECOVERY" | "PREEMPTIVE_WARN"
```

Groq (Llama) is supported as a drop-in alternative to Claude:

```python
from rmic_guard import GroqReasoning
reasoning = GroqReasoning(model_name="groq/llama-3.3-70b-versatile")
```

## CLI

```bash
rmic init research-agent        # scaffold a new agent project (contract + quickstart)
rmic validate contract.json     # check a contract against the schema, no sealing
rmic seal contract.json         # compute anchor_embedding + contract_hash, write back
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

This is an early (0.2.x) release from an active research project on
role-boundary preservation in autonomous agents. APIs may change between
minor versions until 1.0. Issues and contributions welcome on
[GitHub](https://github.com/Arshu-1104/RMIC).

## License

MIT
