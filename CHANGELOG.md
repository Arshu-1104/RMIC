# Changelog

All notable changes to `rmic-guard` are documented here.

## Unreleased

## 0.4.0 — 2026-10-21

### Added

- **Contract hard-rule extensions** (all optional, validated at load, covered by the contract
  hash; contracts without them behave and hash exactly as before):
  - `argument_rules` per tool: `allowed_args` → `BLOCK argument_not_allowed:<tool>:<arg>`;
    full-match `patterns` → `BLOCK argument_pattern:<tool>:<arg>` (strings and numbers, lists
    element-wise, `max_length` cap, regexes ≤ 500 chars compiled at load).
  - `confirm_above` in `parameter_constraints`: new decision `NEEDS_CONFIRMATION` (tool not
    executed, `GuardResult.confirmation_id`); `Guard.confirm()` / `EnforcementEngine.confirm()`
    execute exactly once and log decision `CONFIRMED`; new `ConfirmationNotFoundError`.
  - `deny_patterns` (opt-in heuristics on the user's message): packs `role_reassignment`,
    `objective_override`, `guardrail_removal`, `custom` regexes and `prohibited_terms`; action
    `block` or `warn` (`GuardResult.warnings`); reason `deny_pattern:<pack>:<pattern_id>`.
- New example contract `financial_agent_hardened` (`contracts/examples/` and bundled):
  `financial_agent` + `confirm_above: 10000` + account-format argument patterns. Contract hash
  `1b7e2ad1281b2b100fa219ffd29ca3a1cd67a16ec9886b0a29097ecfd1222904`; `anchor_embedding` is
  byte-identical to `financial_agent`'s (hash recomputed, anchors not re-embedded).
- `PlannedToolCall.user_message` (optional): the end user's words, used by `deny_patterns`.
  `Guard.check()` sets it from `message`, `Guard.run()` from the user message (there
  `raw_text` is the model's output).
- `AuditEntry.confirmation_id` (optional, `null` on other entries); `EnforcementOutcome` gains
  `confirmation_id`, `confirmation_reason` and `warnings`.
- Pending confirmations expire and are capped. TTL: the contract field
  `confirmation_ttl_seconds` (covered by the hash) is a ceiling that
  `Guard(..., confirmation_ttl_seconds=...)` can shorten but not lengthen (a longer value is
  ignored with an `RMICGuardWarning`); without it the `Guard` argument or 600 s applies. At most
  100 pending by default (`Guard(..., max_pending_confirmations=...)`; the oldest is evicted).
  `confirm()` of an expired or evicted id raises `ConfirmationNotFoundError` with `reason`
  `"expired"` / `"evicted"` (`"cancelled"`, `"unknown"` otherwise) and is audited as `BLOCK`
  `confirmation_expired` / `confirmation_evicted` with the same `confirmation_id`.
- `Guard.pending_confirmations()` lists waiting calls (`PendingConfirmation`: id, tool,
  arguments, reason, `created_at`, `expires_at`); `Guard.cancel(confirmation_id)` withdraws one
  and audits it as `BLOCK` `confirmation_cancelled`. Engine equivalents:
  `EnforcementEngine.list_pending_confirmations()` / `.cancel()`.
- `RMICGuardWarning` (a `UserWarning`): `Guard` emits it when it seals a contract in memory
  (pointing to `rmic seal`) and when a longer confirmation TTL is ignored.
- `deny_patterns.max_scan_chars` (default 10,000): only that many leading characters of the user
  message are scanned; longer messages add the warning `deny_pattern_scan_truncated:<N>`
  (also on a deny-pattern `BLOCK`, in `GuardResult.warnings` and the audit `failure_reason`).
- README "Sealing" section: the hash covers `anchor_embedding`, so sealing differs across
  machines and fastembed versions; seal once and distribute sealed files; in-memory auto-seal
  hashes are machine-specific.

- `Guard(..., semantic="monitor")`: the IDS is computed and recorded in `GuardResult`
  (`ids_score`, new `ids_decision` field) and in the audit log (`failure_reason`
  `monitor:would_<decision>` on a `PASS` entry), but never changes a decision. New
  `EnforcementMode` `"monitor"` and `EnforcementOutcome.ids_decision`. The default stays
  `semantic=False`.

### Changed

- `rmic init` seals the scaffolded contract (hash only, offline; `rmic seal` adds the
  embedding), so the generated quickstart loads a sealed contract without a warning.
  `examples/quickstart.py` uses the bundled sealed `financial_agent` contract.
- **In-memory sealing no longer stamps `created_at`** (`load_contract` auto-seal and
  `seal_contract_file` without `write_back`, `Guard` with a path or dict). Loading the same
  unsealed contract twice now gives the same hash (previously the current time made every load
  different). Sealing that writes the file (`rmic seal`, `write_back=True`, `save_sealed=True`)
  still stamps it; already-sealed files are unaffected.
- **Contract hashes: no existing contract changed.** `contracts/*.json` and the bundled copies of
  `financial_agent`, `healthcare_research_agent`, `legal_review_agent` and `support_agent` are
  byte-identical to v0.3 (the research and IBM-pilot contracts must stay reproducible). The only
  new hash is `financial_agent_hardened` (above).
- New decision values `NEEDS_CONFIRMATION` and `CONFIRMED`: code that switches on
  `outcome.decision` / `result.decision` should handle them (`GuardResult.allowed` is False and
  True respectively).
- IDS scoring embeds the scored text once per call (it was embedded once per signal, 7×) and
  each contract's anchor/topic sets once, reusing them across calls. Scores are bit-identical
  (3,200/3,200 component values on the bundled contracts); warm calls take ~8 ms instead of
  ~560–710 ms on the measurement machine (`experiment/perf/ids_latency.md`).
  `ids_metric.set_ids_embedding_cache(False)` restores the uncached path.

### Fixed

- The topic-embedding cache could return vectors from a previous embedding backend after
  `set_embedding_backend()`; cache keys now include the backend generation.

### Repository

Not part of the package.

- `demo.py`, `preflight_check.py` and `seal_contracts.py` moved to `scripts/`.
  `seal_contracts.py` refuses to rewrite the four frozen research contracts unless `--force` is
  passed.
- `run_rmic.py` moved to `ibm_pilot/run_single.py`, which no longer writes the contract file.
- `contracts/_template_universal.json` replaced by `contracts/examples/template.json`, which
  passes `rmic validate`. This changes the experiment's contract-manifest hash for future runs
  only.
- `prompts_v2/` and `prompts_v3/` moved to `prompts/v2/` and `prompts/v3/`. The v1 corpus and its
  manifest hash are unchanged.
- Every top-level folder has a README; the Repository Structure table is updated.
- v0.4 evaluation sets, frozen with SHA-256 hashes:
  - `prompts/external/`: public datasets, selected and mapped by rules committed before
    selection;
  - `prompts/v3/generated/`: model-generated, context-isolated, not human-blind; one contract.
- One evaluation run on these sets, with no tuning: `experiment/eval_v0.4/` (plan, script,
  results, raw CSVs).

## 0.3.0 — 2026-10-21

### Added

- **`rmic_guard.Guard`: a one-call API** on top of the existing classes:

  ```python
  from rmic_guard import Guard

  guard = Guard("contracts/bank_bot.json")
  guard.register("transfer_funds", transfer_funds)          # or @guard.tool
  result = guard.check("transfer_funds", amount=500, to="4321", message="pay rent")
  result = guard.run("Transfer $500 to 4321", llm="groq/llama-3.3-70b-versatile")
  ```

  - Accepts a contract path, dict or `RMICContract`. Unsealed contracts are sealed in
    memory; sealed ones are hash-verified.
  - `check()` builds the `PlannedToolCall` (`data=` → `data_categories_accessed`), keeps the
    per-session IDS score and tool-call history the engine needs, and executes the tool only
    on `PASS` / `PREEMPTIVE_WARN`. `guard.reset()` clears the history and
    `guard.session(id)` returns an isolated session.
  - `run()` plans with `ClaudeReasoning` / `GroqReasoning` (lazy import) and, on
    `NEEDS_RECOVERY`, re-plans with the engine's re-anchoring messages (`max_recovery=1`)
    before blocking.
  - Hard-rules-only by default (`semantic=False`): no embedding model, no network.
    `semantic=True` adds IDS-based identity-drift detection and is **experimental**:
    on the current scoring attacks score lower than legitimate requests (ROC AUC
    0.35–0.49 across the bundled contracts; see
    `experiment/ids_calibration_investigation/post_sep22_threshold_calibration.md`).
  - `audit_log=` / `audit_key=` write every decision to the signed ledger;
    `guard.verify_log()` checks it.
  - `GuardResult` is a frozen dataclass: `allowed`, `decision`, `reason`, `ids_score`,
    `output`, `recovery_attempted`, `contract_hash` (plus `tool_name`, `executed`, `error`
    and the raw `outcome`).
- `AuditLedger` signing keys are now persistent: loaded from `key_path=`, else the
  `RMIC_AUDIT_KEY` environment variable, else `<log>.key` (created with 0600 permissions).
  The public key is written to `<log>.pub`. New `AuditLedger.verify_file(path)` and
  `AuditLedger.verify()`.
- The audit log is hash-chained: each line stores `prev_hash`, the SHA-256 of the previous
  line, inside its signed payload. `verify_file()` therefore detects deleted, inserted and
  reordered lines as well as edits. `AuditLedger.head_hash(path)` returns the last line's
  hash; record it externally to detect truncation of the tail. Lines without `prev_hash`
  (the pre-0.3 format) fail `verify_file()`; `verify_line()` still checks them.
- `load_contract()` seals unsealed contracts automatically (`auto_seal=True` default,
  from PR #5). The new `write_back` flag (default `False`) controls whether the sealed
  contract is written to disk.
- `rmic_guard` now also exports `AuditLedger`, `AuditEntry` and `set_embedding_backend`.
- `load_example_contract()` / `list_example_contracts()` for bundled, pre-sealed example
  contracts.

### Changed — behaviour changes

- **Package layout.** The wheel used to install top-level `core` and `utils` packages, so a
  project with its own `utils.py` could not `import rmic_guard`. They now live at
  `rmic_guard._core` and `rmic_guard._utils`, and only `rmic_guard*` is shipped.
  `from core.planning import PlannedToolCall` (as the 0.2.0 docs showed) must become
  `from rmic_guard import PlannedToolCall`. Every public name is importable from
  `rmic_guard`.
- **`load_contract()` no longer raises `ContractNotSealedError` for an unsealed file**
  by default; it seals it (PR #5). Unlike PR #5's version, sealing on load happens in
  memory only, unless `write_back=True` is passed. Pass `auto_seal=False` for the 0.2.0
  behaviour.
- **IDS scores changed (PR #5, 22 Sep 2026).** `forbidden_topics` passed to the IDS is
  now empty (it used to hold the contract's prohibited data categories and forbidden tool
  names). This lowers `semantic_grounding`, and therefore Base IDS, for practically every
  input, and changes the parallel statistical signals. IDS numbers produced before that
  change are not reproducible with this release.
- **`seal_contract_file()` no longer rewrites the file by default.** `write_back` now
  defaults to `False`: the sealed contract is returned in memory and the file on disk is
  untouched. Pass `write_back=True` (or run `rmic seal <file>`) to persist it. Guard writes
  a sealed contract back only with `save_sealed=True`.
- **Config loading is explicit.** The SDK no longer reads `config.yaml` from the current
  working directory. A config file is used only when passed explicitly or named by the
  `RMIC_CONFIG` environment variable. The repository's research scripts set `RMIC_CONFIG`
  to the repo's `config.yaml` themselves.
- **Contract thresholds are honoured.** `EnforcementEngine` now uses the contract's own
  `ids_warn_threshold` / `ids_block_threshold` / `drift_velocity_threshold`. A config file
  overrides them only when it is explicitly configured and sets the key. Before, built-in
  config defaults (0.35 / 0.60) always masked the contract's values.

### Fixed

- A missing embedding backend now raises `RMICGuardError` that tells you what to install
  (`pip install rmic-guard` / `"rmic-guard[torch]"`) or to use `semantic=False`, instead
  of a bare `ModuleNotFoundError` about `sentence_transformers`.
- The sentence-transformers fallback no longer crashes in `embed_texts()` when fastembed
  cannot load its model.
- `build-system` now requires `setuptools>=77`, which the PEP 639 `license = "MIT"` field
  needs.
- `rmic init` scaffolds a quickstart that uses `Guard` and public imports only.

## 0.2.0

- Beginner API (`RMICContract.create`), explicit contract validation, SDK exception
  hierarchy, `rmic` CLI, offline examples and test suite.
