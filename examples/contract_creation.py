"""Shows both contract-creation API tiers side by side, plus what an
invalid contract's error message looks like.

    python examples/contract_creation.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from core.contract_loader import load_contract, seal_contract_file
from rmic_guard import InvalidContractError, RMICContract


def beginner_api() -> None:
    print("=== Beginner API: RMICContract.create(...) ===")
    contract = RMICContract.create(
        agent_id="support-bot",
        role_name="Support Bot",
        sector="customer_support",
        role_description="Answers product questions from the knowledge base.",
        semantic_anchors=[
            "I answer customer questions using the knowledge base.",
            "I escalate anything I'm unsure about to a human agent.",
        ],
        allowed_actions=["search_kb", "escalate_to_human"],
        forbidden_actions=["issue_refund", "delete_account"],
        require_embedding=False,  # set True (the default) to also compute anchor_embedding
    )
    print(f"agent_id={contract.agent_id!r} contract_hash={contract.contract_hash[:16]}...")
    print("No manual hashing, embedding, or sealing code required.")
    print()


def advanced_api() -> None:
    print("=== Advanced API: raw JSON -> seal_contract_file -> load_contract ===")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "contract.json"
        path.write_text(json.dumps({
            "agent_id": "support-bot-v2",
            "role_name": "Support Bot",
            "sector": "customer_support",
            "semantic_anchors": ["I answer customer questions using the knowledge base."],
            "allowed_actions": ["search_kb"],
        }))
        print(f"Wrote unsealed contract to {path}")

        # anchor_embedding needs a local model on first use; skip in this
        # offline example and go straight to load_contract with hash
        # checking turned off, to show the low-level shape without a
        # network dependency.
        contract = load_contract(path, verify_hash=False)
        print(f"Loaded (unverified): agent_id={contract.agent_id!r}, has_embedding={bool(contract.anchor_embedding)}")
        print("(anchor_embedding is empty because this file was never sealed via")
        print(" seal_contract_file()/RMICContract.create() -- load_contract still works,")
        print(" it just can't be used with EnforcementEngine's 'full'/'ids_only' modes.)")
    print()


def invalid_contract_error_message() -> None:
    print("=== What InvalidContractError looks like ===")
    try:
        RMICContract.create(
            agent_id="broken-bot",
            role_name="",  # missing
            sector="ops",
            semantic_anchors=[],  # empty
            ids_warn_threshold=0.9,
            ids_block_threshold=0.1,  # warn > block, invalid
            require_embedding=False,
        )
    except InvalidContractError as exc:
        print(str(exc))
    print()


if __name__ == "__main__":
    beginner_api()
    advanced_api()
    invalid_contract_error_message()
