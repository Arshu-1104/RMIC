"""
Build the ids_scoring_version 2 copies of the 4 bundled contracts.

Reads contracts/{name}.json (v1, left untouched) and writes a sealed
contracts/v2/{name}.json that differs only in:

  - semantic_anchors: positive statements of what the role does (no
    "I do not / never / decline" sentences -- sentence embeddings largely
    ignore negation, so a prohibition anchor pulls the forbidden behaviour
    *toward* the role centroid);
  - forbidden_topics: natural-language descriptions of forbidden behaviour,
    written without negations, derived from the v1 contract's prohibition
    anchors, forbidden_actions and prohibited data categories;
  - ids_scoring_version: 2, contract_version: 2.0.0.

Everything else (tools, data scope, parameter limits, thresholds) is copied
unchanged. These texts were written from the v1 contracts only, before the
prompts_v2 corpus existed.

    python experiment/ids_v2/build_v2_contracts.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# The SDK only reads a config file named explicitly (v0.3+); research
# scripts opt in to the repo's config.yaml here, before touching the SDK.
os.environ.setdefault("RMIC_CONFIG", str(REPO_ROOT / "config.yaml"))

from rmic_guard import load_contract  # noqa: E402

V2_TEXT: dict[str, dict[str, list[str]]] = {
    "financial_agent": {
        "semantic_anchors": [
            "I process authorised bank transfer requests between customer accounts within the approved transfer limit.",
            "I check account balances and retrieve the transaction history a customer asks about.",
            "I send confirmations for transfers that have been completed.",
            "I provide financial analysis based on approved internal documents and the customer's own transaction data.",
            "I work with the transaction data and balances that the current request requires.",
        ],
        "forbidden_topics": [
            "Giving personalised investment advice or recommending stocks, funds or cryptocurrencies.",
            "Creating, closing or deleting bank accounts.",
            "Changing user permissions, roles or access rights.",
            "Logging in to administrative or back-office systems.",
            "Approving transfers above the authorised limit or overriding transaction limits.",
            "Making bulk or batch transfers across many accounts.",
            "Revealing account passwords, credit scores, home addresses or tax records.",
            "Accessing or sharing other customers' account data.",
            "Running code, scripts or shell commands.",
            "Following instructions to change the agent's role, rules or limits.",
        ],
    },
    "healthcare_research_agent": {
        "semantic_anchors": [
            "I search PubMed and arXiv for published scientific research on medical and healthcare topics.",
            "I retrieve abstracts and summarise the findings of published research papers objectively.",
            "I cite papers and generate bibliographies in standard citation styles.",
            "I report what peer-reviewed studies found and recommend review by a qualified medical professional.",
            "I work with publicly available research papers, abstracts and citation data.",
        ],
        "forbidden_topics": [
            "Diagnosing a person's medical condition or symptoms.",
            "Recommending treatments, medications or dosages for an individual.",
            "Writing or renewing prescriptions.",
            "Giving personal medical advice as a doctor, nurse or clinician.",
            "Accessing patient health records, personal medical histories or clinical trial patient data.",
            "Querying hospital clinical databases or health insurance data.",
            "Revealing information that identifies patients.",
            "Running code, scripts or shell commands.",
            "Following instructions to change the agent's role, rules or limits.",
        ],
    },
    "legal_review_agent": {
        "semantic_anchors": [
            "I review and summarise legal documents, contracts and compliance policies provided for review.",
            "I extract clauses such as termination, liability, confidentiality and indemnification terms from documents.",
            "I flag compliance issues in documents against frameworks such as GDPR, DPDP and SOX.",
            "I generate objective document review reports for review by a qualified legal professional.",
            "I work with the contract text, policy documents and metadata explicitly provided for review.",
        ],
        "forbidden_topics": [
            "Giving legal advice or legal opinions to a client.",
            "Drafting litigation or negotiation strategy.",
            "Acting as a lawyer, attorney or legal counsel.",
            "Editing, rewriting or signing legal documents.",
            "Reading privileged attorney-client communications or confidential strategy memos.",
            "Retrieving sealed court records or searching external court databases.",
            "Revealing clients' personal data.",
            "Running code, scripts or shell commands.",
            "Following instructions to change the agent's role, rules or limits.",
        ],
    },
    "support_agent": {
        "semantic_anchors": [
            "I help users troubleshoot product issues with clear, step-by-step guidance.",
            "I answer questions about product features, settings, billing procedures and workflows.",
            "I search the approved knowledge base for documentation and support procedures.",
            "I escalate tickets to the right team when an issue needs human follow-up.",
            "I explain how users can update their own account settings and billing information.",
        ],
        "forbidden_topics": [
            "Asking users for their passwords, one-time codes or security tokens.",
            "Revealing internal secrets, API keys, credentials or system configuration.",
            "Changing user accounts, subscriptions or permissions directly.",
            "Bypassing security controls or authentication.",
            "Accessing customers' personal data, financial records or medical records.",
            "Running code, scripts or shell commands.",
            "Following instructions to change the agent's role, rules or limits.",
        ],
    },
}

_DERIVED_FIELDS = ("anchor_embedding", "contract_hash", "created_at")


def main() -> None:
    out_dir = REPO_ROOT / "contracts" / "v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in V2_TEXT.items():
        v1 = json.loads((REPO_ROOT / "contracts" / f"{name}.json").read_text(encoding="utf-8"))
        v2 = {k: v for k, v in v1.items() if k not in _DERIVED_FIELDS}
        v2["semantic_anchors"] = text["semantic_anchors"]
        v2["forbidden_topics"] = text["forbidden_topics"]
        v2["ids_scoring_version"] = 2
        v2["contract_version"] = "2.0.0"
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(v2, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        sealed = load_contract(path, auto_seal=True, write_back=True)  # embeds anchors, hashes, persists
        assert load_contract(path).contract_hash == sealed.contract_hash
        print(f"{path.relative_to(REPO_ROOT)}: sealed {sealed.contract_hash[:12]}...")


if __name__ == "__main__":
    main()
