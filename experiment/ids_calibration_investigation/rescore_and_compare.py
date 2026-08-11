"""
Re-score existing stored prompts with the corrected IDS metric functions,
without any new LLM API calls. Uses:
  - exact sealed anchor_embedding from contracts/*.json (reproducible exactly)
  - exact allowed/forbidden topics reconstructed from the same contract
  - stored response_excerpt as a best-effort proxy for the original scoring
    text (note: original text_for_ids also included tool_name + arguments,
    which were not stored separately -- see caveat printed below)

Outputs a before/after AUC comparison per role so you can see whether the
fix actually changes anything before deciding whether it's worth updating
the paper's Table 2 and re-running the ROC analysis on corrected scores.
"""

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from core.ids_metric import (
    mahalanobis_drift,
    wasserstein_drift,
    kl_divergence_drift,
    jensen_shannon_drift,
    hellinger_drift,
    role_distance,
    semantic_grounding,
)

DB_PATH = "results/experiment_results.db"
CONDITION = "C2_ids_only"
CONTRACTS_DIR = Path("contracts")

ROLE_TO_CONTRACT_FILE = {
    "financial_agent": "financial_agent.json",
    "healthcare_research_agent": "healthcare_research_agent.json",
    "legal_review_agent": "legal_review_agent.json",
    "support_agent": "support_agent.json",
}


def load_contract(role: str) -> dict:
    fname = ROLE_TO_CONTRACT_FILE.get(role)
    if fname is None:
        raise ValueError(f"No contract file mapping for role '{role}'")
    path = CONTRACTS_DIR / fname
    with open(path) as f:
        return json.load(f)


def topics_for_contract(contract: dict) -> tuple[list[str], list[str]]:
    allowed = list(contract.get("semantic_anchors", []))
    forbidden: list[str] = []
    data_scope = contract.get("data_scope", {})
    if isinstance(data_scope, dict) and data_scope.get("prohibited"):
        forbidden.extend(data_scope["prohibited"])
    if contract.get("forbidden_actions"):
        forbidden.extend(contract["forbidden_actions"])
    return allowed, forbidden


def main():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT role, response_excerpt, expected_drift "
        "FROM experiment_results WHERE condition = ? AND base_ids IS NOT NULL",
        conn, params=(CONDITION,)
    )
    conn.close()

    print(f"Loaded {len(df)} rows for re-scoring.")
    print("CAVEAT: original scoring text was f'{tool_name} {arguments} {raw_text}';")
    print("only raw_text (as response_excerpt) was stored, so this is a best-effort")
    print("approximation, not a byte-identical replay of the original scoring input.\n")

    contract_cache: dict[str, dict] = {}
    anchor_cache: dict[str, np.ndarray] = {}
    topics_cache: dict[str, tuple[list[str], list[str]]] = {}

    new_mahal = []
    new_wass = []

    total = len(df)
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        role = row["role"]
        text = row["response_excerpt"] or ""

        if role not in contract_cache:
            contract_cache[role] = load_contract(role)
            anchor_cache[role] = np.asarray(contract_cache[role]["anchor_embedding"], dtype=np.float32)
            topics_cache[role] = topics_for_contract(contract_cache[role])

        anchor = anchor_cache[role]
        allowed, forbidden = topics_cache[role]

        m = mahalanobis_drift(text, anchor, allowed_topics=allowed, forbidden_topics=forbidden)
        w = wasserstein_drift(text, anchor, allowed_topics=allowed, forbidden_topics=forbidden)

        new_mahal.append(m)
        new_wass.append(w)

        if i % 50 == 0 or i == total:
            print(f"  processed {i}/{total} rows...")

    df["mahalanobis_fixed"] = new_mahal
    df["wasserstein_fixed"] = new_wass

    df.to_csv("results/rescored_signals.csv", index=False)
    print("Saved full re-scored data to results/rescored_signals.csv\n")

    print("=" * 80)
    print("Coefficient of variation, before vs after fix (higher = more informative spread)")
    print("=" * 80)
    for col_old, col_new, label in [
        ("mahalanobis", "mahalanobis_fixed", "Mahalanobis"),
        ("wasserstein", "wasserstein_fixed", "Wasserstein"),
    ]:
        # Need original values too -- reload them for comparison
        pass

    print("=" * 80)
    print("AUC per role: original signals vs fixed signals")
    print("=" * 80)

    # Reload original columns for side-by-side AUC comparison
    conn = sqlite3.connect(DB_PATH)
    orig = pd.read_sql_query(
        "SELECT rowid, role, mahalanobis, wasserstein, expected_drift "
        "FROM experiment_results WHERE condition = ? AND base_ids IS NOT NULL",
        conn, params=(CONDITION,)
    )
    conn.close()

    df_compare = df.reset_index(drop=True).copy()
    df_compare["mahalanobis_orig"] = orig["mahalanobis"].values
    df_compare["wasserstein_orig"] = orig["wasserstein"].values

    rows = []
    for role, group in df_compare.groupby("role"):
        y = group["expected_drift"].values
        for label, col in [
            ("mahalanobis_orig", "mahalanobis_orig"),
            ("mahalanobis_fixed", "mahalanobis_fixed"),
            ("wasserstein_orig", "wasserstein_orig"),
            ("wasserstein_fixed", "wasserstein_fixed"),
        ]:
            try:
                auc = roc_auc_score(y, group[col].values)
            except ValueError:
                auc = float("nan")
            rows.append({"role": role, "signal": label, "auc": round(auc, 4)})

    result_df = pd.DataFrame(rows)
    pivot = result_df.pivot(index="signal", columns="role", values="auc")
    print(pivot)

    pivot.to_csv("results/rescore_auc_comparison.csv")
    print("\nSaved comparison table to results/rescore_auc_comparison.csv")


if __name__ == "__main__":
    main()
