"""Load, cryptographically seal, and verify RMIC identity contracts.

Two API tiers are exposed:

  Beginner:  RMICContract.create(...)      -- validates, embeds anchors,
                                               hashes, and seals in one call.
  Advanced:  load_contract(...)
             seal_contract_file(...)
             compute_contract_hash(...)     -- direct, low-level access.

Both tiers produce the same frozen RMICContract dataclass.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from rmic_guard._core.exceptions import ContractIntegrityError, ContractNotSealedError, InvalidContractError
from rmic_guard._core.hard_rules import ArgumentRule, DenyPatternConfig, parse_argument_rules, parse_deny_patterns
from rmic_guard._core.validation import validate_contract_dict
from rmic_guard._utils.config import load_config

__all__ = [
    "DataScope",
    "ParameterConstraint",
    "RMICContract",
    "canonical_contract_dict_for_hash",
    "compute_contract_hash",
    "list_example_contracts",
    "load_contract",
    "load_example_contract",
    "seal_contract_file",
    "verify_contract",
]


def canonical_contract_dict_for_hash(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-serialisable dict for hashing (excludes contract_hash only)."""
    return {k: v for k, v in sorted(data.items()) if k != "contract_hash"}


def compute_contract_hash(data: Mapping[str, Any]) -> str:
    """SHA-256 over stable JSON of all fields except contract_hash."""
    payload = canonical_contract_dict_for_hash(dict(data))
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class DataScope:
    """Immutable data-scope slice from the contract JSON."""

    accessible: tuple[str, ...]
    prohibited: tuple[str, ...]
    pii_categories: tuple[str, ...]

    @staticmethod
    def from_mapping(m: Mapping[str, Any]) -> DataScope:
        return DataScope(
            accessible=tuple(m.get("accessible") or ()),
            prohibited=tuple(m.get("prohibited") or ()),
            pii_categories=tuple(m.get("pii_categories") or ()),
        )


@dataclass(frozen=True)
class ParameterConstraint:
    """Single parameter bound as loaded from the contract."""

    name: str
    max: float | int | None
    min: float | int | None
    value_type: str
    # Values above this (and within max) return NEEDS_CONFIRMATION instead of
    # executing. None = no confirmation step.
    confirm_above: float | int | None = None

    @staticmethod
    def from_entry(name: str, spec: Mapping[str, Any]) -> ParameterConstraint:
        return ParameterConstraint(
            name=name,
            max=spec.get("max"),
            min=spec.get("min"),
            value_type=str(spec.get("type", "float")),
            confirm_above=spec.get("confirm_above"),
        )

    def to_spec(self) -> dict[str, Any]:
        spec: dict[str, Any] = {"min": self.min, "max": self.max, "type": self.value_type}
        if self.confirm_above is not None:
            spec["confirm_above"] = self.confirm_above
        return spec


@dataclass(frozen=True)
class RMICContract:
    """Frozen runtime identity contract. No field may change after construction."""

    agent_id: str
    role_name: str
    sector: str
    role_description: str
    semantic_anchors: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    data_scope: DataScope
    parameter_constraints: tuple[ParameterConstraint, ...]
    ids_warn_threshold: float
    ids_block_threshold: float
    drift_velocity_threshold: float
    recovery_policy: str
    compliance_tags: tuple[str, ...]
    contract_version: str
    created_at: str | None
    contract_hash: str
    anchor_embedding: tuple[float, ...]
    # v0.4 hard-rule extensions (see rmic_guard._core.hard_rules). Empty/None
    # when the contract does not define them; never serialised in that case,
    # so contracts without them hash exactly as before.
    argument_rules: tuple[ArgumentRule, ...] = ()
    deny_patterns: DenyPatternConfig | None = None
    # Seconds a NEEDS_CONFIRMATION id stays valid (None: the engine default).
    confirmation_ttl_seconds: float | None = None

    def constraints_by_name(self) -> dict[str, ParameterConstraint]:
        return {c.name: c for c in self.parameter_constraints}

    def to_dict(self) -> dict[str, Any]:
        """Serialise back to the JSON contract shape (round-trips through load_contract).

        anchor_embedding is omitted entirely when empty (not sealed with an
        embedding) rather than written as an empty list or null — this keeps
        the hash-relevant field set identical to what create_contract()/
        seal_contract_file() would have hashed, so contract_hash stays valid
        after a to_dict() -> JSON -> load_contract() round trip.
        """
        d: dict[str, Any] = {
            "agent_id": self.agent_id,
            "role_name": self.role_name,
            "sector": self.sector,
            "role_description": self.role_description,
            "semantic_anchors": list(self.semantic_anchors),
            "allowed_actions": list(self.allowed_actions),
            "forbidden_actions": list(self.forbidden_actions),
            "data_scope": {
                "accessible": list(self.data_scope.accessible),
                "prohibited": list(self.data_scope.prohibited),
                "pii_categories": list(self.data_scope.pii_categories),
            },
            "parameter_constraints": {c.name: c.to_spec() for c in self.parameter_constraints},
            "ids_warn_threshold": self.ids_warn_threshold,
            "ids_block_threshold": self.ids_block_threshold,
            "drift_velocity_threshold": self.drift_velocity_threshold,
            "recovery_policy": self.recovery_policy,
            "compliance_tags": list(self.compliance_tags),
            "contract_version": self.contract_version,
            "created_at": self.created_at,
            "contract_hash": self.contract_hash,
        }
        if self.argument_rules:
            d["argument_rules"] = {r.tool: json.loads(r.raw_json) for r in self.argument_rules}
        if self.deny_patterns is not None:
            d["deny_patterns"] = json.loads(self.deny_patterns.raw_json)
        if self.confirmation_ttl_seconds is not None:
            d["confirmation_ttl_seconds"] = self.confirmation_ttl_seconds
        if self.anchor_embedding:
            d["anchor_embedding"] = list(self.anchor_embedding)
        return d

    # ---- Beginner-friendly high-level API -------------------------------
    #
    # Implemented as create_contract() below and attached to this class at
    # module import time (`RMICContract.create = staticmethod(create_contract)`)
    # so it can be called as `RMICContract.create(...)`. Kept as a plain
    # module-level function too, for callers who prefer `create_contract(...)`.


def _as_tuple_str(v: Any) -> tuple[str, ...]:
    if v is None:
        return ()
    if isinstance(v, str):
        return (v,)
    return tuple(str(x) for x in v)


def _contract_from_dict(data: dict[str, Any], *, require_hash_match: bool, source: str | None = None) -> RMICContract:
    validate_contract_dict(data, source=source)

    cfg = load_config()
    tcfg = cfg.get("thresholds", {})
    stored_hash = data.get("contract_hash")
    if require_hash_match:
        if not stored_hash:
            raise ContractNotSealedError(
                "contract_hash missing; call seal_contract_file(...) or RMICContract.create(...) "
                "before loading with verify_hash=True"
            )
        computed = compute_contract_hash(data)
        if computed != stored_hash:
            raise ContractIntegrityError(
                "contract_hash mismatch — the contract file was modified after sealing, or is "
                "corrupted. Re-seal it if the change was intentional."
            )

    ds_raw = data.get("data_scope") or {}
    pc_raw = data.get("parameter_constraints") or {}

    constraints: list[ParameterConstraint] = []
    for name in sorted(pc_raw.keys()):
        constraints.append(ParameterConstraint.from_entry(name, pc_raw[name]))

    anchors = _as_tuple_str(data.get("semantic_anchors"))

    emb = data.get("anchor_embedding")
    anchor_embedding: tuple[float, ...] = () if emb is None else tuple(float(x) for x in emb)

    return RMICContract(
        agent_id=str(data["agent_id"]),
        role_name=str(data["role_name"]),
        sector=str(data["sector"]),
        role_description=str(data.get("role_description", "")),
        semantic_anchors=anchors,
        allowed_actions=_as_tuple_str(data.get("allowed_actions")),
        forbidden_actions=_as_tuple_str(data.get("forbidden_actions")),
        data_scope=DataScope.from_mapping(ds_raw),
        parameter_constraints=tuple(constraints),
        ids_warn_threshold=float(
            data.get("ids_warn_threshold", data.get("warn_threshold", tcfg.get("warn_threshold", 0.35)))
        ),
        ids_block_threshold=float(
            data.get("ids_block_threshold", data.get("block_threshold", tcfg.get("block_threshold", 0.60)))
        ),
        drift_velocity_threshold=float(
            data.get(
                "drift_velocity_threshold",
                data.get("velocity_threshold", tcfg.get("velocity_threshold", 0.05)),
            )
        ),
        recovery_policy=str(data.get("recovery_policy", "re-anchor")),
        compliance_tags=_as_tuple_str(data.get("compliance_tags")),
        contract_version=str(data.get("contract_version", "1.0.0")),
        created_at=data.get("created_at"),
        contract_hash=str(stored_hash or compute_contract_hash(data)),
        anchor_embedding=anchor_embedding,
        # Already validated by validate_contract_dict above, so these cannot raise.
        argument_rules=parse_argument_rules(
            data.get("argument_rules"), allowed_actions=_as_tuple_str(data.get("allowed_actions"))
        ),
        deny_patterns=parse_deny_patterns(data.get("deny_patterns")),
        # Kept as written (int or float) so to_dict() hashes identically.
        confirmation_ttl_seconds=data.get("confirmation_ttl_seconds"),
    )


def _read_contract_json(p: Path) -> dict[str, Any]:
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidContractError([f"file is not valid JSON: {exc}"], source=str(p)) from exc

    if not isinstance(raw, dict):
        raise InvalidContractError(["contract file must contain a JSON object"], source=str(p))
    return raw


def _write_contract_json(p: Path, data: Mapping[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _seal_dict(
    data: Mapping[str, Any],
    *,
    source: str | None,
    model_name: str | None = None,
    require_embedding: bool = True,
    stamp_created_at: bool = False,
) -> dict[str, Any]:
    """Return a sealed copy of a raw contract dict (never mutates ``data``).

    Validates the pre-seal shape, computes anchor_embedding (when
    require_embedding) and contract_hash. created_at is filled in (when
    missing) only with stamp_created_at, i.e. when the sealed contract is
    written to disk: an in-memory seal must hash the same way on every load.
    """
    sealed = {k: v for k, v in dict(data).items() if k not in ("anchor_embedding", "contract_hash")}
    validate_contract_dict(sealed, source=source)

    if require_embedding:
        from rmic_guard._core.embedder import anchor_centroid_from_anchors

        anchors = _as_tuple_str(sealed.get("semantic_anchors"))
        centroid = anchor_centroid_from_anchors(list(anchors), model_name=model_name)
        sealed["anchor_embedding"] = [float(x) for x in centroid.tolist()]

    if stamp_created_at and sealed.get("created_at") in (None, ""):
        sealed["created_at"] = datetime.now(timezone.utc).isoformat()

    sealed["contract_hash"] = compute_contract_hash(sealed)
    return sealed


def load_contract(
    path: str | Path,
    *,
    verify_hash: bool = True,
    auto_seal: bool = True,
    write_back: bool = False,
    require_embedding: bool = True,
    model_name: str | None = None,
) -> RMICContract:
    """Load a contract JSON file, validate it, and optionally verify SHA-256 integrity.

    auto_seal (default True): when the file has no contract_hash yet, seal it
    on load (embed anchors when require_embedding, hash) instead of raising
    ContractNotSealedError; pass auto_seal=False to get that error instead.
    Sealing happens in memory only; the file on disk is rewritten only if
    write_back=True as well. A file that already carries a contract_hash is
    never re-sealed -- it is verified, so tampering is still detected.
    """
    p = Path(path)
    raw = _read_contract_json(p)
    if auto_seal and not raw.get("contract_hash"):
        sealed = _seal_dict(
            raw,
            source=str(p),
            model_name=model_name,
            require_embedding=require_embedding,
            stamp_created_at=write_back,
        )
        if write_back:
            _write_contract_json(p, sealed)
        return _contract_from_dict(sealed, require_hash_match=True, source=str(p))
    return _contract_from_dict(raw, require_hash_match=verify_hash, source=str(p))


def seal_contract_file(
    path: str | Path,
    *,
    write_back: bool = False,
    model_name: str | None = None,
) -> RMICContract:
    """
    Compute anchor_embedding and contract_hash; optionally persist to disk.

    anchor_embedding is the L2-normalised mean embedding of semantic_anchors.

    Behaviour change in v0.3.0: write_back now defaults to False, so the
    sealed contract is returned in memory and the file on disk is left
    untouched. Pass write_back=True (or run `rmic seal <file>`) to persist it.
    """
    p = Path(path)
    sealed = _seal_dict(_read_contract_json(p), source=str(p), model_name=model_name, stamp_created_at=write_back)
    if write_back:
        _write_contract_json(p, sealed)
    return _contract_from_dict(sealed, require_hash_match=True, source=str(p))


def verify_contract(path: str | Path) -> bool:
    """Advanced API: return True iff the on-disk contract's hash matches its content.

    Never raises on a hash mismatch (unlike load_contract(verify_hash=True)) —
    use this when you just want a boolean check, e.g. from the CLI.
    """
    try:
        load_contract(path, verify_hash=True)
        return True
    except ContractIntegrityError:
        return False


# ---- Beginner-friendly high-level API ------------------------------------

def create_contract(
    *,
    agent_id: str,
    role_name: str,
    sector: str,
    semantic_anchors: list[str],
    role_description: str = "",
    allowed_actions: list[str] | None = None,
    forbidden_actions: list[str] | None = None,
    data_scope: Mapping[str, Any] | None = None,
    parameter_constraints: Mapping[str, Mapping[str, Any]] | None = None,
    ids_warn_threshold: float | None = None,
    ids_block_threshold: float | None = None,
    drift_velocity_threshold: float | None = None,
    recovery_policy: str = "re-anchor",
    compliance_tags: list[str] | None = None,
    contract_version: str = "1.0.0",
    argument_rules: Mapping[str, Mapping[str, Any]] | None = None,
    deny_patterns: Mapping[str, Any] | None = None,
    confirmation_ttl_seconds: float | None = None,
    save_to: str | Path | None = None,
    model_name: str | None = None,
    require_embedding: bool = True,
) -> RMICContract:
    """High-level contract factory: validate -> embed anchors -> hash -> seal.

    Hides contract_hash / anchor_embedding / sealing internals. Raises
    InvalidContractError (listing every problem found) if the inputs don't
    form a valid contract. Pass save_to="contracts/my_agent.json" to also
    persist the sealed contract to disk.

    require_embedding: when True (default), computes anchor_embedding via a
    local sentence-embedding model (downloaded once on first use — see
    rmic_guard._core.embedder.set_embedding_backend to point at a pre-downloaded/offline
    model instead). Semantic drift detection (EnforcementMode "full" /
    "ids_only") needs this. Set to False to skip it entirely and produce a
    contract usable only in EnforcementMode "hard_rules_only" — useful for
    agents that only need forbidden-tool / parameter / data-scope
    enforcement, or for offline contract authoring before a model is
    available.
    """
    from rmic_guard._core.embedder import anchor_centroid_from_anchors

    cfg = load_config()
    tcfg = cfg.get("thresholds", {})
    _ds = dict(data_scope or {})
    normalized_data_scope = {
        "accessible": list(_ds.get("accessible") or []),
        "prohibited": list(_ds.get("prohibited") or []),
        "pii_categories": list(_ds.get("pii_categories") or []),
    }
    data: dict[str, Any] = {
        "agent_id": agent_id,
        "role_name": role_name,
        "sector": sector,
        "role_description": role_description,
        "semantic_anchors": list(semantic_anchors),
        "allowed_actions": list(allowed_actions or []),
        "forbidden_actions": list(forbidden_actions or []),
        "data_scope": normalized_data_scope,
        "parameter_constraints": {k: dict(v) for k, v in (parameter_constraints or {}).items()},
        "ids_warn_threshold": (
            float(ids_warn_threshold) if ids_warn_threshold is not None else float(tcfg.get("warn_threshold", 0.35))
        ),
        "ids_block_threshold": (
            float(ids_block_threshold) if ids_block_threshold is not None else float(tcfg.get("block_threshold", 0.60))
        ),
        "drift_velocity_threshold": (
            float(drift_velocity_threshold)
            if drift_velocity_threshold is not None
            else float(tcfg.get("velocity_threshold", 0.05))
        ),
        "recovery_policy": recovery_policy,
        "compliance_tags": list(compliance_tags or []),
        "contract_version": contract_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Only written when given, so contracts without them hash exactly as before.
    if argument_rules is not None:
        data["argument_rules"] = json.loads(json.dumps(argument_rules))
    if deny_patterns is not None:
        data["deny_patterns"] = json.loads(json.dumps(deny_patterns))
    if confirmation_ttl_seconds is not None:
        data["confirmation_ttl_seconds"] = confirmation_ttl_seconds

    validate_contract_dict(data, source="RMICContract.create(...)")

    if require_embedding:
        centroid = anchor_centroid_from_anchors(list(data["semantic_anchors"]), model_name=model_name)
        data["anchor_embedding"] = [float(x) for x in centroid.tolist()]
    data["contract_hash"] = compute_contract_hash(data)

    if save_to is not None:
        p = Path(save_to)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return _contract_from_dict(data, require_hash_match=True, source="RMICContract.create(...)")


# Attach the beginner API onto the frozen dataclass so `RMICContract.create(...)` works.
RMICContract.create = staticmethod(create_contract)


# Bundled, pre-sealed example contracts (loadable with zero setup, zero
# network call -- they ship already sealed with contract_hash/anchor_embedding
# baked in). Shipped as package data under rmic_guard/examples/ (see
# pyproject.toml [tool.setuptools.package-data]) so this works identically
# in a repo checkout and a `pip install rmic-guard` install.
_EXAMPLE_CONTRACTS = (
    "financial_agent",
    "healthcare_research_agent",
    "legal_review_agent",
    "support_agent",
    # financial_agent + confirm_above and account-format argument patterns
    # (v0.4); a copy of contracts/examples/financial_agent_hardened.json.
    "financial_agent_hardened",
)


def list_example_contracts() -> tuple[str, ...]:
    """Names usable with load_example_contract(name)."""
    return _EXAMPLE_CONTRACTS


def load_example_contract(name: str) -> RMICContract:
    """Load one of the bundled, pre-sealed example contracts by name.

    >>> from rmic_guard import load_example_contract
    >>> contract = load_example_contract("financial_agent")

    No network call: these contracts are already sealed, so this works
    fully offline immediately after `pip install rmic-guard`, with no LLM
    key and no contract-writing required. See list_example_contracts().
    """
    if name not in _EXAMPLE_CONTRACTS:
        available = ", ".join(_EXAMPLE_CONTRACTS)
        raise ValueError(f"Unknown example contract {name!r}. Available: {available}")

    import importlib.resources as resources

    ref = resources.files("rmic_guard.examples").joinpath(f"{name}.json")
    with resources.as_file(ref) as path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))

    return _contract_from_dict(data, require_hash_match=True, source=f"load_example_contract({name!r})")