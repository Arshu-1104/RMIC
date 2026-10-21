# Changelog

All notable changes to `rmic-guard` are documented here.

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
  - `semantic=False` gives hard-rules-only mode: no embedding model, no network.
  - `audit_log=` / `audit_key=` write every decision to the signed ledger;
    `guard.verify_log()` checks it.
  - `GuardResult` is a frozen dataclass: `allowed`, `decision`, `reason`, `ids_score`,
    `output`, `recovery_attempted`, `contract_hash` (plus `tool_name`, `executed`, `error`
    and the raw `outcome`).
- `AuditLedger` signing keys are now persistent: loaded from `key_path=`, else the
  `RMIC_AUDIT_KEY` environment variable, else `<log>.key` (created with 0600 permissions).
  The public key is written to `<log>.pub`. New `AuditLedger.verify_file(path)` and
  `AuditLedger.verify()`.
- `load_contract(..., auto_seal=True, write_back=False)` seals an unsealed contract on load.
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
