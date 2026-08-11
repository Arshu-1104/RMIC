"""
Experiment 2: does the raw embedding space separate adversarial from
legitimate prompts at all, independent of any hand-designed distance
formula?

Trains a classifier (logistic regression + a small MLP for comparison)
directly on the 384-dim BGE embedding of each prompt's response_excerpt,
per role, with proper train/test split. This is the cleanest possible
test: if this also fails, the issue isn't the formulas (role_distance,
mahalanobis, etc.) -- it's that this embedding model's representation
doesn't separate these two classes for this corpus, full stop.
"""

import sqlite3
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from core.embedder import embed_texts

DB_PATH = "results/experiment_results.db"
CONDITION = "C2_ids_only"


def main():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT role, response_excerpt, expected_drift "
        "FROM experiment_results WHERE condition = ? AND base_ids IS NOT NULL",
        conn, params=(CONDITION,)
    )
    conn.close()

    print(f"Loaded {len(df)} rows. Embedding all texts (this reuses the cached model, should be fast)...\n")

    texts = df["response_excerpt"].fillna("").tolist()
    embeddings = embed_texts(texts)  # shape (n, 384)
    print(f"Embedded shape: {embeddings.shape}\n")

    results = []
    for role in df["role"].unique():
        mask = (df["role"] == role).values
        X = embeddings[mask]
        y = df.loc[mask, "expected_drift"].values

        if len(np.unique(y)) < 2 or mask.sum() < 30:
            print(f"{role}: skipped (insufficient data)")
            continue

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y
        )

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        # Logistic regression on raw embeddings
        lr = LogisticRegression(max_iter=2000, C=1.0)
        lr.fit(X_train_s, y_train)
        auc_lr = roc_auc_score(y_test, lr.predict_proba(X_test_s)[:, 1])

        # Small MLP, in case the boundary is non-linear
        mlp = MLPClassifier(hidden_layer_sizes=(64,), max_iter=1000, random_state=42)
        mlp.fit(X_train_s, y_train)
        auc_mlp = roc_auc_score(y_test, mlp.predict_proba(X_test_s)[:, 1])

        results.append({
            "role": role,
            "n_train": len(X_train),
            "n_test": len(X_test),
            "AUC_logistic_raw_embeddings": round(auc_lr, 4),
            "AUC_mlp_raw_embeddings": round(auc_mlp, 4),
        })

        print(f"{role}: LR AUC={auc_lr:.4f}, MLP AUC={auc_mlp:.4f} "
              f"(n_train={len(X_train)}, n_test={len(X_test)})")

    result_df = pd.DataFrame(results)
    result_df.to_csv("results/raw_embedding_classifier_auc.csv", index=False)
    print("\nSaved to results/raw_embedding_classifier_auc.csv")
    print("\nInterpretation guide:")
    print("  AUC ~0.5        -> embedding space genuinely does not separate these classes")
    print("  AUC 0.6-0.75    -> weak but real signal exists, worth pursuing further")
    print("  AUC 0.85+       -> strong signal exists; the hand-designed formulas were the problem")


if __name__ == "__main__":
    main()
