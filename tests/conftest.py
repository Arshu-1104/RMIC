"""Shared fixtures for the RMIC-Guard test suite.

Tests never hit a real embedding model or network — a deterministic,
content-sensitive fake embedding backend is installed for the whole
session via core.embedder.set_embedding_backend(). It is NOT a stand-in
for the real semantic model's quality; it only needs to be internally
consistent (same text -> same vector, similar text -> similar vector)
so that role_distance / semantic_grounding behave sensibly enough to
exercise PASS/WARN/BLOCK branching deterministically in CI.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.embedder import set_embedding_backend

_DIM = 64


def _char_ngram_embed(texts: list[str]) -> np.ndarray:
    """Deterministic bag-of-trigrams hash embedding — no model, no network."""
    out = np.zeros((len(texts), _DIM), dtype=np.float32)
    for i, text in enumerate(texts):
        t = text.lower()
        grams = [t[j : j + 3] for j in range(max(1, len(t) - 2))] or [t]
        for g in grams:
            out[i, hash(g) % _DIM] += 1.0
    return out


@pytest.fixture(autouse=True, scope="session")
def _deterministic_embeddings() -> None:
    set_embedding_backend(_char_ngram_embed)
    yield
    set_embedding_backend(None)
