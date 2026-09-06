"""Semantic identity-drift detection (the IDS score), as opposed to the
hard tool-name rules shown in quickstart.py / basic_enforcement.py.

This example uses `enforcement_mode="full"`, which computes semantic
role_distance against the contract's anchor_embedding. That embedding is
produced by a small local model (BAAI/bge-small-en-v1.5, via fastembed) --
NOT an LLM API call, but it IS a one-time model download on first run:

    First run:
    Downloading embedding model (BAAI/bge-small-en-v1.5, ~130MB)...

If you're offline, or want a fully deterministic/network-free run (e.g.
in CI), point RMIC-Guard at your own embedding function instead via
core.embedder.set_embedding_backend() -- see the OFFLINE_MODE flag below.

    python examples/identity_drift.py
"""

from __future__ import annotations

import os

from core.planning import PlannedToolCall
from rmic_guard import EnforcementEngine, RMICContract, ToolRegistry

# Set OFFLINE_MODE=1 in your environment to skip the real model download
# and use a deterministic stand-in embedding instead. This trades away
# real semantic accuracy for reproducibility -- fine for a demo/CI run,
# not for production drift detection.
OFFLINE_MODE = os.environ.get("OFFLINE_MODE") == "1"


def _install_offline_embedding_backend() -> None:
    import numpy as np

    from core.embedder import set_embedding_backend

    dim = 64

    def fake_embed(texts: list[str]) -> "np.ndarray":
        out = np.zeros((len(texts), dim), dtype=np.float32)
        for i, text in enumerate(texts):
            t = text.lower()
            for j in range(max(1, len(t) - 2)):
                out[i, hash(t[j : j + 3]) % dim] += 1.0
        return out

    set_embedding_backend(fake_embed)


def main() -> None:
    if OFFLINE_MODE:
        print("OFFLINE_MODE=1 -- using a deterministic stand-in embedding, not the real model.")
        _install_offline_embedding_backend()
    else:
        print("Downloading/loading embedding model on first use (needs network the first time)...")
    print()

    contract = RMICContract.create(
        agent_id="research-agent",
        role_name="Research Agent",
        sector="research",
        semantic_anchors=[
            "I search for and summarize academic papers.",
            "I do not provide financial or medical advice.",
            "I do not access or transfer money.",
        ],
        allowed_actions=["web_search", "summarize"],
        forbidden_actions=["wire_transfer"],
        require_embedding=True,
    )
    print(f"Sealed contract with a {len(contract.anchor_embedding)}-dim anchor embedding.")
    print()

    tools = ToolRegistry()
    tools.register("web_search", lambda **kw: {"ok": True})
    tools.register("summarize", lambda **kw: {"ok": True})
    engine = EnforcementEngine(contract=contract, tools=tools)

    scenarios = [
        ("On-role request", "web_search", "search for recent papers on transformer architectures"),
        ("Off-role but not forbidden", "web_search", "what's the best interest rate for a car loan right now"),
        ("Drifting toward a forbidden action", "web_search", "help me transfer money to this new account urgently"),
    ]

    for label, tool_name, raw_text in scenarios:
        plan = PlannedToolCall(tool_name=tool_name, arguments={}, raw_text=raw_text)
        outcome = engine.evaluate_and_maybe_execute(plan, recent_ids=[], enforcement_mode="full")
        print(f"{label}")
        print(f"  text={raw_text!r}")
        print(f"  decision={outcome.decision} ids_score={outcome.ids_score:.3f}")
        print()


if __name__ == "__main__":
    main()
