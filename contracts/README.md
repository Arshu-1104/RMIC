# contracts/

Sealed identity contracts for the four research agent roles, plus example contracts.

| File | What it is |
|---|---|
| `financial_agent.json`, `healthcare_research_agent.json`, `legal_review_agent.json`, `support_agent.json` | The research contracts used by the experiment, the paper and the IBM pilot. **Frozen:** keep them byte-identical (`scripts/seal_contracts.py` refuses to re-seal them without `--force`). Bundled in the package as `load_example_contract(name)`. |
| `examples/financial_agent_hardened.json` | `financial_agent` plus the v0.4 hard-rule extensions (`confirm_above`, argument patterns). Bundled as `load_example_contract("financial_agent_hardened")`. |
| `examples/template.json` | A minimal, unsealed starting point for your own contract (below). |

## Using the template

Copy `examples/template.json`, edit it, check it with `rmic validate my_agent.json`, then
seal it once with `rmic seal my_agent.json` and distribute the sealed file (see the README's
"Sealing" section). Its fields:

| Field | Meaning |
|---|---|
| `agent_id`, `role_name`, `sector` | Required identifiers. `agent_id` appears in every audit-log entry. |
| `role_description` | Free text describing the role. |
| `semantic_anchors` | Required. First-person sentences describing in-role behaviour; semantic mode embeds them. |
| `allowed_actions` | Tool names the agent may call. If non-empty, any other tool is blocked (`tool_not_allowed`). |
| `forbidden_actions` | Tool names that are always blocked (`forbidden_tool`). |
| `data_scope` | `accessible` / `prohibited` data categories; touching a prohibited one blocks (`data_scope:prohibited:<category>`). `pii_categories` is descriptive. |
| `parameter_constraints` | Numeric bounds per argument name: `min`, `max`, `type` (`int` / `float`), optional `confirm_above`. |
| `contract_version` | Semantic version of the contract. |

Optional fields that the template leaves at their defaults: `ids_warn_threshold`,
`ids_block_threshold`, `drift_velocity_threshold`, `recovery_policy`, `compliance_tags`,
`argument_rules`, `deny_patterns`, `confirmation_ttl_seconds`. The full reference is
[`schema/contract.schema.json`](../schema/contract.schema.json).
