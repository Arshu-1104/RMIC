"""Explicit validation for RMIC contract dictionaries.

Runs BEFORE any deeper processing (embedding, hashing, sealing) so that a
malformed contract fails fast with a message that says what is wrong,
where, and how to fix it — instead of a bare KeyError/TypeError surfacing
from deep inside contract_loader.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping

from core.exceptions import InvalidContractError

__all__ = ["validate_contract_dict", "REQUIRED_FIELDS"]

REQUIRED_FIELDS: tuple[str, ...] = (
    "agent_id",
    "role_name",
    "sector",
    "semantic_anchors",
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SEMVER_LIKE = re.compile(r"^\d+\.\d+\.\d+$")


def _is_str_list(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _check_string(problems: list[str], data: Mapping[str, Any], field: str, *, required: bool) -> None:
    if field not in data or data.get(field) in (None, ""):
        if required:
            problems.append(f"{field}: missing required field (expected a non-empty string)")
        return
    if not isinstance(data[field], str):
        problems.append(f"{field}: must be a string, got {type(data[field]).__name__}")


def _check_str_list(
    problems: list[str], data: Mapping[str, Any], field: str, *, required: bool, allow_empty: bool = True
) -> None:
    if field not in data or data.get(field) is None:
        if required:
            problems.append(f"{field}: missing required field (expected a list of strings)")
        return
    v = data[field]
    if not _is_str_list(v):
        problems.append(f"{field}: must be a list of strings, e.g. [\"item_one\", \"item_two\"]")
        return
    if not allow_empty and len(v) == 0:
        problems.append(f"{field}: must contain at least one entry")


def _check_threshold(problems: list[str], data: Mapping[str, Any], field: str) -> None:
    if field not in data or data.get(field) is None:
        return
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        problems.append(f"{field}: must be a number between 0.0 and 1.0, got {v!r}")
        return
    if not (0.0 <= float(v) <= 1.0):
        problems.append(f"{field}: must be between 0.0 and 1.0, got {v}")


def _check_data_scope(problems: list[str], data: Mapping[str, Any]) -> None:
    if "data_scope" not in data or data.get("data_scope") is None:
        return
    ds = data["data_scope"]
    if not isinstance(ds, dict):
        problems.append("data_scope: must be an object with accessible/prohibited/pii_categories lists")
        return
    for sub in ("accessible", "prohibited", "pii_categories"):
        if sub in ds and ds[sub] is not None and not _is_str_list(ds[sub]):
            problems.append(f"data_scope.{sub}: must be a list of strings")


def _check_parameter_constraints(problems: list[str], data: Mapping[str, Any]) -> None:
    if "parameter_constraints" not in data or data.get("parameter_constraints") is None:
        return
    pc = data["parameter_constraints"]
    if not isinstance(pc, dict):
        problems.append(
            "parameter_constraints: must be an object mapping parameter name -> "
            '{"min": ..., "max": ..., "type": "float"|"int"}'
        )
        return
    for name, spec in pc.items():
        if not isinstance(spec, dict):
            problems.append(f"parameter_constraints.{name}: must be an object with min/max/type")
            continue
        vtype = spec.get("type", "float")
        if vtype not in ("float", "int"):
            problems.append(
                f'parameter_constraints.{name}.type: must be "float" or "int", got {vtype!r}'
            )
        lo, hi = spec.get("min"), spec.get("max")
        for bound_name, bound in (("min", lo), ("max", hi)):
            if bound is not None and not isinstance(bound, (int, float)):
                problems.append(f"parameter_constraints.{name}.{bound_name}: must be numeric")
        if lo is not None and hi is not None and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            if lo > hi:
                problems.append(
                    f"parameter_constraints.{name}: min ({lo}) is greater than max ({hi})"
                )


def _check_semantic_anchors(problems: list[str], data: Mapping[str, Any]) -> None:
    anchors = data.get("semantic_anchors")
    if anchors is None:
        problems.append(
            "semantic_anchors: missing required field (expected a non-empty list of "
            'first-person role-description sentences, e.g. ["I perform research tasks."])'
        )
        return
    if not _is_str_list(anchors):
        problems.append("semantic_anchors: must be a list of strings")
        return
    if len(anchors) == 0:
        problems.append("semantic_anchors: must contain at least one sentence")
        return
    for i, a in enumerate(anchors):
        if not a.strip():
            problems.append(f"semantic_anchors[{i}]: must not be an empty/whitespace-only string")


def _check_contract_version(problems: list[str], data: Mapping[str, Any]) -> None:
    if "contract_version" not in data or data.get("contract_version") is None:
        return
    v = data["contract_version"]
    if not isinstance(v, str) or not _SEMVER_LIKE.match(v):
        problems.append(
            f'contract_version: must be a semantic version string like "1.0.0", got {v!r}'
        )


def _check_created_at(problems: list[str], data: Mapping[str, Any]) -> None:
    v = data.get("created_at")
    if v is None:
        return
    if not isinstance(v, str):
        problems.append("created_at: must be an ISO-8601 timestamp string")
        return
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        problems.append(
            f"created_at: {v!r} is not a valid ISO-8601 timestamp "
            '(e.g. "2026-01-15T09:30:00+00:00")'
        )


def _check_contract_hash(problems: list[str], data: Mapping[str, Any]) -> None:
    v = data.get("contract_hash")
    if v is None:
        return
    if not isinstance(v, str) or not _HEX64.match(v):
        problems.append("contract_hash: must be a 64-character hex SHA-256 digest if present")


def _check_anchor_embedding(problems: list[str], data: Mapping[str, Any]) -> None:
    v = data.get("anchor_embedding")
    if v is None:
        return
    if not isinstance(v, list) or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        problems.append("anchor_embedding: must be a list of floats (produced by seal_contract_file)")
    elif len(v) == 0:
        problems.append("anchor_embedding: present but empty — re-seal the contract")


def validate_contract_dict(data: Mapping[str, Any], *, source: str | None = None) -> None:
    """Validate a raw contract dict before any embedding/hashing/sealing work.

    Raises InvalidContractError (with every problem found, not just the
    first) if the contract is malformed. Returns None on success.
    """
    if not isinstance(data, Mapping):
        raise InvalidContractError([f"contract must be a JSON object, got {type(data).__name__}"], source=source)

    problems: list[str] = []

    for field in REQUIRED_FIELDS:
        if field == "semantic_anchors":
            continue  # handled by the richer check below
        _check_string(problems, data, field, required=True)

    _check_semantic_anchors(problems, data)
    _check_string(problems, data, "role_description", required=False)
    _check_str_list(problems, data, "allowed_actions", required=False)
    _check_str_list(problems, data, "forbidden_actions", required=False)
    _check_str_list(problems, data, "compliance_tags", required=False)
    _check_data_scope(problems, data)
    _check_parameter_constraints(problems, data)
    _check_threshold(problems, data, "ids_warn_threshold")
    _check_threshold(problems, data, "ids_block_threshold")
    if (
        isinstance(data.get("ids_warn_threshold"), (int, float))
        and isinstance(data.get("ids_block_threshold"), (int, float))
        and float(data["ids_warn_threshold"]) > float(data["ids_block_threshold"])
    ):
        problems.append(
            "ids_warn_threshold must be <= ids_block_threshold "
            f"(got warn={data['ids_warn_threshold']}, block={data['ids_block_threshold']})"
        )
    if "drift_velocity_threshold" in data and data.get("drift_velocity_threshold") is not None:
        dv = data["drift_velocity_threshold"]
        if isinstance(dv, bool) or not isinstance(dv, (int, float)) or dv < 0:
            problems.append("drift_velocity_threshold: must be a non-negative number")
    _check_string(problems, data, "recovery_policy", required=False)
    _check_contract_version(problems, data)
    _check_created_at(problems, data)
    _check_contract_hash(problems, data)
    _check_anchor_embedding(problems, data)

    if problems:
        raise InvalidContractError(problems, source=source)
