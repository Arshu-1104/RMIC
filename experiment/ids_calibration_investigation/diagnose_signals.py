"""
Two checks:
1. Does any single one of the 7 IDS signals separate adversarial from
   legitimate better than base_ids does alone?
2. Does a combined logistic regression over all 7 signals (the actual
   remedy proposed in the paper's SS5.5, "fitting a logistic boundary
   on held-out labeled data") achieve real separation, per role?

This uses simple train/test split per role rather than a single
threshold sweep, since we're now testing a *classifier*, not a
single-variable threshold.
"""

import sqlite3
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

DB_PATH = "results/experiment_results.db"
CONDITION = "C2_ids_only"

SIGNAL_COLS = [
    "base_ids", "mahalanobis", "kl_divergence",
    "js_divergence", "wasserstein", "hellinger", "tool_frequency",
]

conn = sqlite3.connect(DB_PATH)
df = pd.read_sql_query(
    "SELECT * FROM experiment_results WHERE condition = ? AND base_ids IS NOT NULL",
    conn, params=(CONDITION,)
)
conn.close()

print("=" * 80)
print("PART 1: Individual signal AUC per role (single-variable, using all rows)")
print("=" * 80)

results = []
for role, group in df.groupby("role"):
    y = group["expected_drift"].values
    for col in SIGNAL_COLS:
        if col not in group.columns or group[col].isna().all():
            continue
        x = group[col].values
        try:
            auc = roc_auc_score(y, x)
        except ValueError:
            auc = np.nan
        results.append({"role": role, "signal": col, "auc": auc})

signal_df = pd.DataFrame(results)
pivot = signal_df.pivot(index="signal", columns="role", values="auc")
print(pivot.round(3))

print()
print("=" * 80)
print("PART 2: Combined logistic regression over all 7 signals, per role")
print("(80/20 train/test split, AUC reported on held-out test set)")
print("=" * 80)

for role, group in df.groupby("role"):
    available_cols = [c for c in SIGNAL_COLS if c in group.columns and not group[c].isna().all()]
    X = group[available_cols].fillna(group[available_cols].mean())
    y = group["expected_drift"]

    if y.nunique() < 2 or len(group) < 20:
        print(f"{role}: skipped (insufficient data or single class)")
        continue

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    clf = LogisticRegression(max_iter=1000)
    clf.fit(X_train, y_train)
    probs = clf.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, probs)

    coefs = dict(zip(available_cols, clf.coef_[0]))
    print(f"\n{role}: held-out AUC = {auc:.4f}  (n_train={len(X_train)}, n_test={len(X_test)})")
    print("  Feature coefficients:")
    for feat, c in sorted(coefs.items(), key=lambda kv: -abs(kv[1])):
        print(f"    {feat:16s} {c:+.3f}")
