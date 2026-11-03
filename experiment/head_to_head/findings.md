## Findings (written after the run; nothing was tuned)

- **With equivalent policies, the three frameworks made the same decision on every item.**
  Across 15,317 items (145 external, 87 generated, 13,085 real-world, the 2 Gandalf calls
  standing for 2,000 attack checks), rmic-guard, AgentSpec and Progent stopped the same attacks
  (72/80, 37/45, 0/2,000), stopped the same legitimate items (56/65, 0/42, 95/13,083) and sent
  the same 95 Banking77 transfers for confirmation. 145/145, 87/87 and 13,085/13,085 items had
  the same outcome in all three.
- **So on these sets rmic-guard's hard rules add no enforcement power.** What a role contract
  expresses (allow and deny lists, argument patterns, numeric bounds, a confirmation threshold,
  a session total) can be written as AgentSpec rules or, except the session total, as a static
  Progent policy, and enforced the same way. rmic-guard's difference is packaging: one sealed,
  hash-verified contract per role (48–106 lines here), validated at load, with a hash-chained
  audit log, reused unchanged across tasks and models.
- **The frameworks differ on edge cases that the evaluation sets do not contain** (synthetic
  probes written by the authors):
  - *Renamed argument* (`Amount=999999`): rmic-guard blocks (argument names are matched
    case-insensitively since 0.4.2; 0.4.1 would have let it through). An AgentSpec predicate
    written against `amount` lets it run. Progent skips restrictions on absent arguments, so
    the allow policy passes it, but the confirmation policy also matches a call without
    `amount` and asks a human.
  - *NaN amount*: rmic-guard blocks (since 0.4.2). Progent's JSON Schema bounds accept NaN, and
    the call reaches a human confirmation. The AgentSpec result depends on how the predicate
    is written; `not (lo <= v <= hi)` blocks it, `v > hi or v < lo` would not.
  - *Session total* (6 × 9,000 against a 50,000 limit): rmic-guard and AgentSpec (whose
    predicates see `intermediate_steps`) block the sixth transfer. A static Progent policy sees
    one call at a time and lets all six run.
  - *Unlisted or misspelled tool*: rmic-guard and Progent deny by default. AgentSpec rules
    fire on exact tool names, so a tool without a rule runs unchecked unless the host agent
    rejects the unknown name itself.
- **Cost.** All three check a call in well under a millisecond (median: rmic-guard 0.034 ms,
  Progent 0.069 ms, AgentSpec 0.78 ms; AgentSpec re-parses each triggered rule on every call).
- **Policy size** is similar for the financial contracts (rmic-guard 69–106 lines, Progent
  58–154, AgentSpec 130–230 lines of rules plus shared predicate code). AgentSpec needs one deny
  rule per unlisted tool, so its rule text grows with the agent's tool set.

## Limits

- The translations are ours, written from each framework's documented policy language. A
  different author could write different AgentSpec predicates (see NaN above).
- Only deterministic enforcement was compared. AgentSpec's `llm_self_reflect` and LLM rule
  generation, Progent's LLM-generated and updated policies, and Task Shield (an LLM judge)
  need a live model and were not run.
- `data_scope` is not exercised by these sets and is not expressible in a static Progent
  policy.

## Run log

- The single run (commit `c29a603`) completed all items and probes.
- The two probes `tool_name_case` and `unknown_tool` deviated from the plan, because the run
  added their tool names to AgentSpec's tool set. They were re-run once as planned
  (`probes_correction.csv`), and both results are reported. No evaluation item was re-run.
- `results.md` was rebuilt with `run_h2h.py --report` to add that correction and to fix the
  policy-size caption. The CSVs are unchanged.
