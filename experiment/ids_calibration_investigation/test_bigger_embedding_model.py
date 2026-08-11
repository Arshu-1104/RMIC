"""
Experiment 3: does a larger embedding model capture more of the
adversarial-vs-legitimate distinction than BGE-small (384-dim)?

Tests BAAI/bge-base-en-v1.5 (768-dim) as a step up. If your fastembed
version supports it, this also tries bge-large-en-v1.5 (1024-dim).
Uses the identical cross-validated logistic regression methodology as
final_roc_cv_classifier.py so results are directly comparable.

NOTE: this re-embeds all 1334 texts with a bigger model, which is
somewhat slower than bge-small but still fully local/free -- expect a
few minutes, not hours.
"""

import sqlite3
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

from fastembed import TextEmbedding

DB_PATH = "results/experiment_results.db"
CONDITION = "C2_ids_only"
N_FOLDS = 5

MODELS_TO_TRY = [
    "BAAI/bge-base-en-v1.5",
    "BAAI/bge-large-en-v1.5",
]


def embed_with_model(texts, model_name):
    model = TextEmbedding(model_name)
    embeddings = list(model.embed(texts))
    arr = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return arr / norms


def evaluate_model(embeddings, df):
    rows = []
    for role in df["role"].unique():
        mask = (df["role"] == role).values
        X = embeddings[mask]
        y = df.loc[mask, "expected_drift"].values
        if len(np.unique(y)) < 2 or mask.sum() < 30:
            continue
        clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
        cv = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=42)
        oof_probs = cross_val_predict(clf, X, y, cv=cv, method="predict_proba")[:, 1]
        auc = roc_auc_score(y, oof_probs)
        rows.append({"role": role, "auc": round(auc, 4)})
    return rows


def main():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT role, response_excerpt, expected_drift "
        "FROM experiment_results WHERE condition = ? AND base_ids IS NOT NULL",
        conn, params=(CONDITION,)
    )
    conn.close()
    texts = df["response_excerpt"].fillna("").tolist()

    print("Baseline (bge-small, already computed previously):")
    print("  financial_agent=0.5831  support_agent=0.6005  "
          "healthcare_research_agent=0.5213  legal_review_agent=0.6498\n")

    all_results = {}
    for model_name in MODELS_TO_TRY:
        print(f"Trying {model_name} ...")
        try:
            embeddings = embed_with_model(texts, model_name)
        except Exception as e:
            print(f"  FAILED to load {model_name}: {e}")
            print(f"  (this model may need `pip install --upgrade fastembed` "
                  f"or isn't available in your fastembed version -- skipping)\n")
            continue

        print(f"  Embedded shape: {embeddings.shape}")
        rows = evaluate_model(embeddings, df)
        all_results[model_name] = rows
        for r in rows:
            print(f"  {r['role']}: AUC = {r['auc']}")
        print()

    summary = []
    for model_name, rows in all_results.items():
        for r in rows:
            summary.append({"model": model_name, **r})
    if summary:
        pd.DataFrame(summary).to_csv("results/embedding_model_comparison.csv", index=False)
        print("Saved comparison to results/embedding_model_comparison.csv")


if __name__ == "__main__":
    main()
