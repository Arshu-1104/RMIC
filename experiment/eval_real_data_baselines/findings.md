## Findings (written after the run; nothing was tuned)

- **ProtectAI is far better at recognising injection wording.**
  - It flagged all 1,000 Gandalf prompts (100%, 95% CI 99.6–100), including all 112 in the test
    split. rmic-guard (b) caught 32 (3.2%).
  - On the same prompts, ProtectAI caught 968 that rmic-guard (b) missed. rmic-guard (b) caught
    none that ProtectAI missed.
- **The price is about 16 times more false alarms on ordinary banking queries:** ProtectAI
  flagged 706 of 13,083 Banking77 queries (5.4%), rmic-guard (b) 45 (0.3%).
  - ProtectAI's flags spread over 59 of the 77 intents and concentrate on card and PIN questions:
    `get_physical_card` 54%, `passcode_forgotten` 46%, `pin_blocked` 39%, `card_arrival` 22%.
  - Its score separates the two sets almost perfectly (ROC AUC 0.999). A stricter threshold would
    keep 97.7% of attacks at a 1% false-positive rate, but the plan fixed the default threshold, so
    the summary uses it.
- **The two barely overlap on false alarms.** Only 1 Banking77 query was flagged by both.
  rmic-guard (b)'s 45 come mostly (38) from its `be_a_role` pattern; ProtectAI's 706 come
  from different queries. Combining them (flag if either flags) catches 100% of attacks with
  5.7% false alarms.
- **Speed.** rmic-guard (b) takes about 0.03 ms per check. ProtectAI takes 23 ms (median, p95
  171 ms) on this machine's CPU, roughly 770 times slower, but still fast enough for most agents.
- **Overlap with training data is unknown.** ProtectAI's training data was not checked against
  Gandalf. A near-perfect score on a public attack set can partly reflect having seen similar
  data.

**In one sentence:** for spotting injection wording, the existing open-source classifier is much
better than rmic-guard's deny patterns. rmic-guard's job is different: deterministic checks on
tools and arguments, which these text-only attacks never trigger. The two are complements, not
substitutes.
