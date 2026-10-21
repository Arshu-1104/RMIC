# prompts/v3/generated/

**Model-generated, context-isolated, not human-blind.** Secondary evaluation set for v0.4.

These files were written by fresh Claude subagents on 2026-10-21. Each one received only:
`prompts/v3/README.md` (the brief), `prompts/*.json` (the v1 corpus), and the
`role_description`, `semantic_anchors` and `allowed_actions` of the four research contracts,
all pasted into its instructions. Each was told not to use any tools or read any files. None of
them saw the deny patterns, the argument rules, `experiment/`, `prompts/v2/`, `contracts/examples/`,
the README or the conversation that wrote the rules.

This is not the human-blind set that `prompts/v3/README.md` describes. The generator is a
language model of the same family as the one that wrote the rules, so its phrasing may resemble
theirs. Treat its results as secondary to the external set in `prompts/external/`.

| Contract | Status |
|---|---|
| `legal_review_agent.json` | Generated; saved unedited: 45 attacks (9 per category), 42 legitimate, 4 warm-up turns. |
| `financial_agent` | **Not produced.** A safety classifier stopped the generation partway, and the subagent was told not to regenerate that content. It was not retried. |
| `healthcare_research_agent` | **Not produced**, for the same reason. |
| `support_agent` | **Not produced**, for the same reason. |

So for three contracts there is no secondary set. Their human-written blind sets are still
outstanding, as described in `prompts/v3/README.md`.

The file has no review (`review.json`) and no `FROZEN` record in the sense of the brief. It is
frozen by its SHA-256 in `prompts/external/SHA256SUMS`, in the commit "freeze evaluation sets v0.4".
