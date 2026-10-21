"""Configuration loader with safe defaults for RMIC-Guard.

The SDK only reads a YAML config when one is named explicitly -- either as
the ``path`` argument or via the ``RMIC_CONFIG`` environment variable. It
never picks up a ``config.yaml`` from the current working directory: until
v0.2.0 it did, so any unrelated config.yaml in a user's project silently
changed RMIC thresholds and IDS weights.

The research scripts in this repository (experiment/, baselines/,
ibm_pilot/, scripts/) opt in to the repo's config.yaml by
setting RMIC_CONFIG before they touch the SDK.
"""

from __future__ import annotations

import copy
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "model": {
        "provider": "anthropic",
        "anthropic_model": "anthropic/claude-sonnet-4-6",
        "anthropic_haiku_model": "anthropic/claude-haiku-4-5",
        "groq_model": "groq/llama-3.3-70b-versatile",
        "groq_mixtral_model": "groq/llama-3.1-8b-instant",
        "temperature": 0.2,
        "max_tokens": 1024,
        "rate_limits": {
            "anthropic_rps": 1.0,
            "groq_rps": 0.5,
        },
        "retry": {
            "max_attempts": 3,
            "backoff_factor": 2.0,
            "max_backoff_seconds": 30.0,
        },
    },
    "ids": {
        "weights": {
            "role_distance": 0.4,
            "semantic_grounding": 0.4,
            "trajectory_curvature": 0.2,
        },
        "ablation_mode": "full",
        "trajectory_window_size": 5,
    },
    "thresholds": {
        "warn_threshold": 0.35,
        "block_threshold": 0.60,
        "velocity_threshold": 0.05,
    },
    "experiment": {
        "multi_model_mode": True,
        "models_to_test": [
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-haiku-4-5",
            "groq/llama-3.3-70b-versatile",
            "groq/llama-3.1-8b-instant",
        ],
        "providers_to_test": ["anthropic", "groq"],
        "ensure_identical_prompts": True,
        "conditions": [
            "B_prompt_contract",
            "C_rmic_middleware",
            "C1_hard_rules_only",
            "C2_ids_only",
        ],
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


CONFIG_ENV_VAR = "RMIC_CONFIG"


def _resolve_config_path(path: str | Path | None) -> Path | None:
    if path is not None:
        return Path(path)
    env = (os.environ.get(CONFIG_ENV_VAR) or "").strip()
    return Path(env) if env else None


@lru_cache(maxsize=8)
def _read_config_file(path_str: str) -> dict[str, Any]:
    cfg_path = Path(path_str)
    if not cfg_path.is_file():
        raise FileNotFoundError(
            f"RMIC config file not found: {cfg_path} "
            f"(passed explicitly or via the {CONFIG_ENV_VAR} environment variable)"
        )
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def load_user_config(path: str | Path | None = None) -> dict[str, Any]:
    """Return only the explicitly configured values (no defaults merged in).

    Empty when neither ``path`` nor ``RMIC_CONFIG`` is set. Callers use this
    to tell "the user configured X" apart from "X is a built-in default".
    """
    resolved = _resolve_config_path(path)
    if resolved is None:
        return {}
    return copy.deepcopy(_read_config_file(str(resolved)))


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """DEFAULT_CONFIG deep-merged with the explicit config (if any)."""
    return _deep_merge(copy.deepcopy(DEFAULT_CONFIG), load_user_config(path))


def clear_config_cache() -> None:
    """Forget cached config file contents (e.g. after editing the file)."""
    _read_config_file.cache_clear()


# Backwards compatibility: load_config used to be an lru_cache'd function.
load_config.cache_clear = clear_config_cache  # type: ignore[attr-defined]
