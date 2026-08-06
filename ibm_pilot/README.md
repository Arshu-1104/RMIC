# IBM watsonx Orchestrate RMIC-Guard Pilot

> **Status: this pilot has since been deployed live** to a real watsonx
> Orchestrate trial instance and verified end-to-end in a live agent
> conversation. See [`LIVE_DEPLOYMENT.md`](LIVE_DEPLOYMENT.md) for the
> live architecture, results, and a demo video. The rest of this
> document describes the original local-simulation pilot that preceded
> the live deployment; Sections 11–12 below are now historical and are
> superseded by `LIVE_DEPLOYMENT.md`.

## 1. Project Overview

RMIC-Guard is a runtime enforcement system built around machine-checkable identity contracts for autonomous AI agents. Rather than relying on prompt-level instructions alone, RMIC-Guard validates each planned agent action against a formally defined identity contract at runtime, allowing or blocking the action before it executes. This closes a common gap in agent deployments where an agent's behavior can drift away from its intended role, permissions, or operating boundaries over the course of a session.

The purpose of this pilot is to validate RMIC-Guard's enforcement pipeline against IBM watsonx Orchestrate, an external agent orchestration framework. By wrapping the existing RMIC enforcement engine as a watsonx Orchestrate tool, this pilot demonstrates that RMIC-Guard's identity contract validation can be embedded into a third-party agent runtime without modifying the underlying enforcement logic.

Runtime machine-checkable identity contracts protect AI agents from identity drift by defining, in a structured and verifiable format, what an agent is permitted to do, which tools it may call, and under what conditions. Every planned action is checked against this contract before execution. Actions that conform to the contract are allowed to proceed; actions that violate it — such as unauthorized permission escalation or behavior inconsistent with the agent's declared identity — are blocked and recorded, rather than being executed and discovered after the fact.

This pilot serves as validation evidence that RMIC-Guard's enforcement model is portable across agent orchestration frameworks. It confirms that the core enforcement engine, contract loader, and audit ledger can be reused as-is, with only a thin adapter layer required to interface with IBM watsonx Orchestrate's tool-calling conventions.

## 2. Architecture Overview

The pilot follows this execution flow:

```
User Request
→ IBM watsonx Orchestrate Agent
→ RMIC Guard Tool
→ Existing RMIC Enforcement Engine
→ Identity Contract Validation
→ ALLOW/BLOCK Decision
→ Tool Execution or Rejection
→ Signed Audit Ledger
```

A user request is received by an agent running inside IBM watsonx Orchestrate. Before the agent executes a planned action, it invokes the RMIC Guard Tool, which acts as an adapter into the existing RMIC repository. The RMIC Guard Tool forwards the request into the existing RMIC Enforcement Engine, which validates it against the relevant identity contract. The engine returns an ALLOW or BLOCK decision. If the decision is ALLOW, the underlying tool action is permitted to execute; if BLOCK, the action is rejected. In both cases, the outcome is recorded in the signed audit ledger.

Critically, this pilot reuses the existing RMIC repository components — the enforcement engine, contract loader, reasoning layer, and audit ledger — rather than rewriting enforcement logic for IBM watsonx Orchestrate. The IBM pilot code is limited to the adapter and demonstration layer needed to connect an Orchestrate agent to the existing enforcement pipeline.

## 3. Folder Structure

Only the following verified files and directories are part of this pilot and its supporting repository:

```
RMIC/
├── core/
│   ├── enforcement_engine.py
│   ├── contract_loader.py
│   ├── audit_ledger.py
│   ├── reasoning_layer.py
│   └── tool_layer.py
│
├── contracts/
│   └── financial_agent.json
│
├── ibm_pilot/
│   ├── rmic_guard_tool.py
│   ├── agent_example.py
│   ├── demo.py
│   └── test_rmic_guard.py
│
├── dashboard/
├── evaluation/
├── experiment/
├── utils/
│
├── config.yaml
├── setup.py
├── seal_contracts.py
└── requirements.txt
```

## 4. IBM Pilot Components

### ibm_pilot/rmic_guard_tool.py

This module acts as the adapter between IBM watsonx Orchestrate agent requests and the existing RMIC enforcement pipeline. It converts incoming Orchestrate requests into the request structures expected by the existing RMIC codebase, calls the existing `EnforcementEngine`, and returns a structured ALLOW/BLOCK response back to the calling agent. No enforcement logic is duplicated here — this module is purely a translation and integration layer.

### ibm_pilot/agent_example.py

This module registers RMIC Guard as a watsonx Orchestrate Python tool. It uses the IBM ADK tool decorator to expose the RMIC Guard adapter in a form that an Orchestrate agent can call directly. This allows an Orchestrate agent to invoke RMIC validation before carrying out an action, ensuring the identity contract check happens as part of the agent's normal planning and execution flow.

### ibm_pilot/demo.py

This script provides a local demonstration of the complete pipeline, from request through enforcement decision. It uses the existing reasoning layer for planning and exercises four scenarios:

1. Valid financial transaction → ALLOW
2. Valid account lookup → ALLOW
3. Permission escalation → BLOCK
4. Identity drift attack → BLOCK

### ibm_pilot/test_rmic_guard.py

This module contains automated pytest validation for the pilot. It tests valid requests, invalid requests, contract validation, tool validation, and audit logging, providing regression coverage for the adapter layer against the existing RMIC enforcement engine.

## 5. Installation

Create a virtual environment:

```
python -m venv .venv
```

Activate the environment:

Windows:

```
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```
pip install -r requirements.txt
```

Install the testing dependency:

```
pip install pytest
```

## 6. Environment Setup

The pilot requires an API key configured for the model provider used by the reasoning layer. This key should be supplied using a `.env` file, with either `GROQ_API_KEY` or `ANTHROPIC_API_KEY` set depending on which model provider has been configured. No additional environment variables are required for this pilot.

## 7. Running the Demo

Seal the identity contracts before running the demo:

```
python seal_contracts.py
```

Run the pilot demo:

```
python ibm_pilot/demo.py
```

Running the demo executes the four scenarios described in Section 4 against the existing RMIC enforcement engine via the IBM pilot adapter, printing the expected and actual ALLOW/BLOCK decision for each scenario.

## 8. Running Tests

Set the Python path:

```
$env:PYTHONPATH="."
```

Run the pilot test suite:

```
pytest ibm_pilot/test_rmic_guard.py -v
```

Validated result: **11 tests passed**.

## 9. Expected Demo Output

```
RMIC-Guard x IBM watsonx Orchestrate — local pilot demo

Valid financial transaction:
Expected: ALLOW
Actual decision: ALLOW

Valid account lookup:
Expected: ALLOW
Actual decision: ALLOW

Permission escalation:
Expected: BLOCK
Actual decision: BLOCK

Identity drift attack:
Expected: BLOCK
Actual decision: BLOCK
```

## 10. IBM watsonx Orchestrate Integration Explanation

Within IBM watsonx Orchestrate, the integration works as follows: the IBM agent plans an action in response to a user request. Before that action is executed, RMIC Guard validates the planned action against the relevant identity contract using the existing RMIC enforcement engine. Only approved actions are allowed to proceed to execution. Actions that fail validation are rejected and recorded in the audit ledger rather than being executed. In this arrangement, RMIC Guard acts as a runtime identity enforcement layer sitting between the Orchestrate agent's planning step and its tool execution step.

## 11. Limitations (as of the local-simulation pilot)

- This section described the local-simulation pilot before a live
  deployment existed. **This has since been superseded** — see
  [`LIVE_DEPLOYMENT.md`](LIVE_DEPLOYMENT.md), which documents an actual
  deployment to a hosted watsonx Orchestrate instance, its own
  limitations (a simplified keyword-based drift check in place of the
  full semantic IDS scoring, no persistent audit ledger, manual contract
  sync), and live-verified results.
- Session state handling across multi-turn Orchestrate agent
  interactions has not been addressed by either the local or live
  pilot and would need further consideration for production use.
- Additional production-hardening requirements (hosting the full
  enforcement engine as an installable package rather than a
  sandbox-inlined stand-in, managed audit storage, enterprise identity
  integration) remain open — see `LIVE_DEPLOYMENT.md` Section 4 and
  "Option B" discussion for the path to running the *full* engine
  live rather than the pilot-scope standalone tool.

## 12. What Actually Happened Next

The "Future IBM Cloud Deployment" work originally sketched in this
section has been completed: RMIC-Guard was deployed as a real tool
(`ibm_pilot/orchestrate_tool_standalone.py`) inside a live watsonx
Orchestrate trial instance, wired to a deployed agent
(`ibm_pilot/rmic_financial_agent.yaml`), and verified against all four
test scenarios in a live chat conversation. Full details, architecture
differences from this local pilot, and results are in
[`LIVE_DEPLOYMENT.md`](LIVE_DEPLOYMENT.md).

Remaining future work: replacing the sandbox-inlined rule check with
the full `core/` enforcement engine running as an installable package
(see `LIVE_DEPLOYMENT.md`'s "Option B" discussion), and adding
persistent audit storage for the live deployment.