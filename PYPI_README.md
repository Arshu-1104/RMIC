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

If your platform can't run `fastembed`'s ONNX backend, install the
PyTorch-based fallback instead:

```bash
pip install "rmic-guard[torch]"
```

## Quickstart

```python
from rmic_guard import load_contract, EnforcementEngine, ClaudeReasoning

# 1. Load a role contract (see contracts/*.json in the repo for examples)
contract = load_contract("contracts/financial_agent.json")

# 2. Plan a tool call from a user message
reasoning = ClaudeReasoning()  # reads ANTHROPIC_API_KEY from the environment
plan = reasoning.plan_tool_call(
    "What's my current account balance?",
    contract=contract,
    condition="C",
)

# 3. Enforce the contract before executing
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

Groq (Llama/Mixtral) is supported as a drop-in alternative to Claude:

```python
from rmic_guard import GroqReasoning
reasoning = GroqReasoning(model_name="groq/llama-3.3-70b-versatile")
```

## Writing a contract

A contract is a JSON file describing the agent's role, its allowed and
forbidden tools, parameter constraints, and data-access scope. See the
`contracts/` directory in the [GitHub repo](https://github.com/Charithra207/RMIC-guard)
for real examples across financial, support, healthcare-research, and
legal-review agent roles.

## Status

This is an early (0.1.x) release from an active research project on
role-boundary preservation in autonomous agents. APIs may change between
minor versions until 1.0. Issues and contributions welcome on GitHub.

## License

MIT