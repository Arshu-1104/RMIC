## Findings (written after the run; nothing was tuned)

- **Hard rules don't catch text-only attacks, as expected.** Condition (a) blocked 0 of 1,000
  Gandalf prompts. Each was paired with an allowed, in-limit action, and hard rules only look at
  tools and arguments. On Banking77, (a) blocked nothing and sent 95 transfers (0.7%) for
  confirmation: their seeded amounts were above 10,000. 99.3% of the queries completed.
- **The deny patterns caught few attacks and blocked some ordinary queries.**
  - They blocked 32 of 1,000 Gandalf prompts (3.2%) and 2 of the 112 in the test split.
  - The packs target role reassignment ("you are now…", "act as…"). Most Gandalf prompts are
    generic overrides ("ignore your instructions", "forget your directive", "what are your
    instructions?") or password-extraction tricks, which the packs have no pattern for.
  - Another 134 attack checks (67 prompts) matched `objective_override`, which is set to warn,
    so they ran.
- **Most false positives came from one pattern.** 45 of 13,083 Banking77 queries were blocked
  (0.3%):
  - 38 by `role_reassignment:be_a_role` (`\bbe (?:my|a|an) [\w-]+`), which matches ordinary
    phrasing such as "will there be a fee", "be a certain age" or "should be a bit higher";
  - 3 by `skip_verification`, 2 by `act_as` (e.g. "an answer as to why"), 1 by `as_my_role` and
    1 by `bypass`.

  The pattern was not changed: this run is the measurement. A fix belongs in a later release,
  which a new run would then evaluate.
- **The IDS doesn't separate these attacks from these queries.** ROC AUC was 0.448 over all
  checks, below chance: 0.385 within `transfer_funds` and 0.658 within `check_balance`. At a 1%
  Banking77 false-positive rate it flags 2.1% of attack checks. With `semantic=True` at the
  contract's thresholds it would have stopped 5 of 2,000 attack checks and 7 of 13,083 queries.
  This matches the v0.4 result: semantic mode stays monitor-only.
- **Latency.** The rule-only conditions take about 0.02–0.03 ms per check (median). Computing
  the IDS adds about 5 ms (median 4.8 ms, p95 9.7 ms) on this machine, after the one-off model
  load.

## Run log

- The single run (commit `76c3db0`) completed all 45,249 checks (15,083 × 3 conditions) and
  wrote `results.csv`. The chart step then crashed: a float-rounding artefact made one error
  bar slightly negative.
- That was fixed by clamping error bars at 0, and `results.md` and `results.png` were rebuilt
  from the unchanged `results.csv` with `run_eval.py --report`. No check was re-run.
- The paraphrases (`paraphrases.json`) and this file were written after the run.
