"""Local sentence embeddings for IDS and sealed anchor centroid."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np

from rmic_guard._core.exceptions import RMICGuardError

__all__ = [
    "DEFAULT_MODEL_NAME",
    "anchor_centroid_from_anchors",
    "cosine_similarity",
    "embed_texts",
    "get_model",
    "get_embedding_backend",
    "normalise_l2",
    "set_embedding_backend",
]

DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"  # fastembed model name; downloaded once on first semantic use

# Optional injection point: point this at a pre-downloaded/offline model, a
# remote embedding API, or a deterministic stub for tests — without touching
# any other RMIC-Guard code. See section 20 of the packaging notes: this is
# the "embedding_provider=..." escape hatch so a caller can make first-run
# network behaviour explicit instead of implicit.
#
#     from rmic_guard._core.embedder import set_embedding_backend
#     set_embedding_backend(lambda texts: my_own_embed_fn(texts))
#
# The callable takes list[str] and must return an (n, dim) float32 array;
# embed_texts() L2-normalises the result for you.
_embedding_backend: Any = None


def set_embedding_backend(fn: Any | None) -> None:
    """Install (or clear, with None) a custom embedding callable.

    fn(texts: list[str]) -> np.ndarray of shape (len(texts), dim). When set,
    embed_texts() calls this instead of loading fastembed/sentence-transformers,
    so no network access or local model file is required.
    """
    global _embedding_backend
    _embedding_backend = fn


def get_embedding_backend() -> Any | None:
    return _embedding_backend


_INSTALL_HINT = (
    'Install one with `pip install rmic-guard` (ships fastembed) or '
    '`pip install "rmic-guard[torch]"` (sentence-transformers), or skip semantic '
    "drift detection entirely with Guard(..., semantic=False) / "
    "RMICContract.create(..., require_embedding=False) (hard rules only, no model, no network)."
)


@lru_cache(maxsize=4)
def get_model(model_name: str | None = None) -> Any:
    """Return a fastembed TextEmbedding model, or SentenceTransformer if fastembed is unavailable.

    Raises RMICGuardError (not a bare ModuleNotFoundError) when neither
    backend can be imported.
    """
    resolved_name = model_name or DEFAULT_MODEL_NAME
    fastembed_problem: BaseException | None = None
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        fastembed_problem = exc
    else:
        # First call per model_name downloads it once, then fastembed/HF caches
        # it locally -- this print makes that first-run pause visible instead of
        # a silent multi-second/minute hang with no feedback.
        print(
            f"[rmic-guard] Loading embedding model '{resolved_name}' "
            f"(first run downloads it once, then it's cached locally)...",
            flush=True,
        )
        try:
            return TextEmbedding(resolved_name)
        except OSError as exc:
            fastembed_problem = exc

    try:
        from sentence_transformers import SentenceTransformer as ST
    except ImportError as exc:
        if isinstance(fastembed_problem, ImportError):
            reason = "neither fastembed nor sentence-transformers is installed"
        else:
            reason = (
                f"fastembed could not load '{resolved_name}' ({fastembed_problem}) and "
                "sentence-transformers is not installed as a fallback"
            )
        raise RMICGuardError(
            f"Semantic drift detection needs a local embedding model, but {reason}. {_INSTALL_HINT}"
        ) from exc

    return ST(model_name or "all-MiniLM-L6-v2")


def embed_texts(texts: list[str], model_name: str | None = None) -> np.ndarray:
    """Return L2-normalised embeddings, shape (n, dim)."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    if _embedding_backend is not None:
        arr = np.asarray(_embedding_backend(texts), dtype=np.float32)
    else:
        # get_model() is lru_cache'd: reusing the instance is the difference
        # between ~1-3s and ~1-3ms per call once warm.
        model = get_model(model_name)
        if hasattr(model, "embed"):  # fastembed
            arr = np.array(list(model.embed(texts)), dtype=np.float32)
        else:  # sentence-transformers fallback
            arr = np.asarray(
                model.encode(texts, convert_to_numpy=True, show_progress_bar=False),
                dtype=np.float32,
            )
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (arr / norms).astype(np.float32)


def normalise_l2(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n == 0.0:
        return v
    return (v / n).astype(np.float32)


def anchor_centroid_from_anchors(
    semantic_anchors: list[str],
    model_name: str | None = None,
) -> np.ndarray:
    """Mean of anchor embeddings, then L2-normalised (single centroid vector)."""
    e = embed_texts(semantic_anchors, model_name=model_name)
    if e.size == 0:
        raise ValueError("semantic_anchors is empty")
    centroid = np.mean(e, axis=0).astype(np.float32)
    return normalise_l2(centroid)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for L2-normalised vectors equals dot product."""
    return float(np.dot(np.asarray(a, dtype=np.float32).ravel(), np.asarray(b, dtype=np.float32).ravel()))