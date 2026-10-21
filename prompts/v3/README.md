# prompts/v3: blind test set (instructions for writers)

This folder will hold a test set written by people who have **not** seen RMIC-Guard's rules.
Every number we have for the hard-rule extensions so far comes from `prompts/v2`, which was
written by the same person who wrote the rules. Those numbers are therefore optimistic: the
held-out split has already been used to design the rules, and even the tune split shares the
rule author's phrasing. `prompts/v3` exists to give one honest measurement. That only works if
its writers stay blind and the set is evaluated exactly once.

## 1. Who can write it

- People who have **not** read, and will not read until the evaluation is published, any of the
  files listed in "Do not read" below.
- At least **two writers**, each writing for at least two of the four contracts, so that no
  contract's set reflects a single person's style.
- A **reviewer** (who can be one of the writers, but not for their own items) checks the labels
  (see section 5).
- The person who **runs** the evaluation must not edit the corpus, the rules or the contracts
  afterwards (see section 6).

## 2. Do not read (until the results are published)

- `rmic_guard/_core/hard_rules.py`, `rmic_guard/_core/enforcement_engine.py` and
  `rmic_guard/_core/validation.py`
- `contracts/examples/` (in particular `financial_agent_hardened.json`) and `contracts/v2/`
  (on the `v0.4-ids-scoring` branch)
- everything under `experiment/hard_rule_gaps/`, `experiment/ids_v2/` and
  `experiment/ids_calibration_investigation/`
- `prompts/v2/`
- the README section "Contract hard-rule extensions", the PyPI README section of the same name,
  and the "Unreleased" part of `CHANGELOG.md`
- the git history and pull requests of the `v0.4-hardening` and `v0.4-ids-scoring` branches

If you have already seen any of these, say so; you can still review labels, but don't write items.

## 3. What you may read

- The four research contracts in `contracts/` (`financial_agent`, `healthcare_research_agent`,
  `legal_review_agent`, `support_agent`). They tell you each agent's role, its allowed and
  forbidden tools, its data scope and its parameter limits. That is what a real attacker or user
  would know about the agent.
- `prompts/*.json` (the original v1 corpus; **not** `prompts/v2/`) as an example of drift categories, but **do not copy or
  paraphrase** its items.
- The "Item format" section below.

## 4. What to write

For **each** of the four contracts, one file `prompts/v3/<contract>.json` containing:

- **At least 40 attacks**, at least 8 in each drift category:
  - `role_drift`: the agent is asked to take on a different role;
  - `goal_drift`: its objective is replaced;
  - `persona_drift`: its persona or tone is replaced;
  - `permission_drift`: it is asked to exceed its permissions;
  - `data_scope_drift`: it is asked for data outside its scope.
- In each category, **at least 2 multi-turn escalation sequences** (2–5 turns) where early
  turns look legitimate.
- Vary the wording as much as you naturally would: polite requests, indirect requests, requests
  embedded in a story, requests split across turns, requests in plain business language. Don't
  aim at any particular phrasing; you don't know what the rules look for, and that is the point.
- **At least 40 legitimate requests** a real user of that agent would make, at least 8 of them
  multi-turn. Include hard but legitimate cases: large amounts within the limits, questions that
  mention passwords, security or other people for a good reason, unusual but allowed tools.
- **4 warm-up turns**: ordinary in-role requests used only as session context.

Each turn carries the tool call the agent would plan if it complied with the message. Use the
contract's tool names, or a plausible tool that is not listed when the request needs one. Choose
argument names and values the way an LLM agent writing free-form JSON would; don't copy them
from any other file. If you generate plans with an LLM instead of writing them, record the model,
the prompt and the date in the file's `description`.

## 5. Item format

The same JSON shape as `prompts/v2` uses. Every field shown is required except `args` and `data`.

```json
{
  "contract": "support_agent",
  "description": "Who wrote it, when, and how plans were produced.",
  "writers": ["initials-1", "initials-2"],
  "warmup": [
    {"message": "...", "tool": "search_kb", "args": {"query": "..."}}
  ],
  "attacks": [
    {"id": "role_drift_01", "category": "role_drift", "writer": "initials-1", "turns": [
      {"message": "...", "tool": "answer_query", "args": {"topic": "..."}, "data": []}
    ]}
  ],
  "legitimate": [
    {"id": "legit_01", "writer": "initials-2", "turns": [
      {"message": "...", "tool": "search_kb", "args": {"query": "..."}}
    ]}
  ]
}
```

- `data` lists the data categories the call touches, using the contract's `data_scope` names,
  only when the planned call would actually access them.
- **Labels:** the reviewer reads every item and marks disagreements in a separate
  `prompts/v3/review.json` (`{"<contract>/<id>": "comment"}`). Items the writer and reviewer
  can't agree on are removed before freezing, and the count of removed items is reported.

## 6. Freezing and evaluating (once)

1. When all four files and the review are done, **commit them in one commit** and record that
   commit's hash in `prompts/v3/FROZEN` together with the date. From then on, the files in this
   folder must not change.
2. Someone who is not the rule author then runs the evaluation **once**, at a recorded commit of
   the code. The evaluation scripts are adapted to read `prompts/v3` only after the freeze, and
   that adaptation is committed separately before the run.
3. The results are published as they come out, including bad ones. Changing a rule, a pattern,
   a threshold or a contract after seeing them makes `prompts/v3` a tuning set: any later claim
   then needs a new blind set (`prompts/v4`, same procedure).
4. Nobody tunes on `prompts/v3`. Nobody looks at individual results before the full run is
   published.
