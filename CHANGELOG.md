# Changelog

All notable changes to `rmic-guard` are documented here.

## Unreleased (v0.4-hardening)

### Added

- `Guard(..., semantic="monitor")`: the IDS is computed and recorded in `GuardResult`
  (`ids_score`, new `ids_decision` field) and in the audit log (`failure_reason`
  `monitor:would_<decision>` on a `PASS` entry), but never changes a decision. New
  `EnforcementMode` `"monitor"` and `EnforcementOutcome.ids_decision`. The default stays
  `semantic=False`.

### Changed

- IDS scoring embeds the scored text once per call (it was embedded once per signal, 7×) and
  each contract's anchor/topic sets once, reusing them across calls. Scores are bit-identical
  (3,200/3,200 component values on the bundled contracts); warm calls take ~8 ms instead of
  ~560–710 ms on the measurement machine (`experiment/perf/ids_latency.md`).
  `ids_metric.set_ids_embedding_cache(False)` restores the uncached path.

### Fixed

- The topic-embedding cache could return vectors from a previous embedding backend after
  `set_embedding_backend()`; cache keys now include the backend generation.

## 0.3.0 — unreleased

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
