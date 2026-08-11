"""
Final ROC curve generation: uses stratified k-fold cross-validation to
get out-of-fold predicted probabilities from a logistic regression
trained on raw embeddings, per role. This avoids the optimistic bias of
evaluating on the same data a model was fit on, and gives a more stable
AUC estimate than a single train/test split given our modest per-role
sample sizes (~300-350 rows).

This IS the "fitting a logistic boundary on held-out labeled data"
remedy the paper already proposes in SS5.5 -- this script is the first
time it's actually been implemented and tested end-to-end.
"""

import sqlite3
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

from core.embedder import embed_texts

DB_PATH = "results/experiment_results.db"
CONDITION = "C2_ids_only"
N_FOLDS = 5


def main():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT role, response_excerpt, expected_drift "
        "FROM experiment_results WHERE condition = ? AND base_ids IS NOT NULL",
        conn, params=(CONDITION,)
    )
    conn.close()

    print(f"Loaded {len(df)} rows. Embedding all texts...\n")
    texts = df["response_excerpt"].fillna("").tolist()
    embeddings = embed_texts(texts)

    plt.figure(figsize=(7, 6))
    summary_rows = []

    for role in df["role"].unique():
        mask = (df["role"] == role).values
        X = embeddings[mask]
        y = df.loc[mask, "expected_drift"].values

        if len(np.unique(y)) < 2 or mask.sum() < 30:
            print(f"{role}: skipped (insufficient data)")
            continue

        clf = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=2000, C=1.0)
        )

        cv = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=42)
        oof_probs = cross_val_predict(clf, X, y, cv=cv, method="predict_proba")[:, 1]

        auc = roc_auc_score(y, oof_probs)
        fpr, tpr, thresholds = roc_curve(y, oof_probs)

        # Best operating point subject to FPR <= 0.05
        valid = fpr <= 0.05
        if valid.any():
            best_idx = np.argmax(tpr[valid])
            best_fpr = fpr[valid][best_idx]
            best_tpr = tpr[valid][best_idx]
            best_thresh = thresholds[valid][best_idx]
        else:
            best_fpr = best_tpr = best_thresh = None

        summary_rows.append({
            "role": role,
            "AUC_cv": round(auc, 4),
            "n": int(mask.sum()),
            "best_DSR_at_FPR<=0.05": round(best_tpr, 4) if best_tpr is not None else None,
            "best_FPR": round(best_fpr, 4) if best_fpr is not None else None,
            "best_threshold": round(float(best_thresh), 4) if best_thresh is not None else None,
        })

        plt.plot(fpr, tpr, marker=".", markersize=3, linewidth=1.5,
                  label=f"{role} (AUC={auc:.3f})")

        print(f"{role}: cross-validated AUC = {auc:.4f}  (n={mask.sum()})")
        if best_tpr is not None:
            print(f"    at FPR<=0.05: DSR={best_tpr:.3f}, FPR={best_fpr:.3f}, threshold={best_thresh:.3f}")
        else:
            print(f"    NO threshold in this fold achieves FPR<=0.05")

    plt.plot([0, 1], [0, 1], "--", color="gray", linewidth=1, label="Chance")
    plt.axvline(0.05, linestyle=":", color="red", linewidth=1, label="FPR = 0.05 target")
    plt.xlabel("False Positive Rate (FPR)")
    plt.ylabel("Drift Suppression Rate / TPR (DSR)")
    plt.title("Cross-validated logistic classifier on raw embeddings, per role")
    plt.legend(loc="lower right", fontsize=8)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig("results/roc_curves_trained_classifier.png", dpi=200)
    print("\nSaved plot to results/roc_curves_trained_classifier.png")

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv("results/roc_trained_classifier_summary.csv", index=False)
    print("\nSummary:")
    print(summary_df.to_string(index=False))
    print("\nSaved to results/roc_trained_classifier_summary.csv")


if __name__ == "__main__":
    main()
