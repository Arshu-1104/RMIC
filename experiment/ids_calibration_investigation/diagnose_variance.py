"""
Checks whether each signal actually varies meaningfully across prompts
at all (regardless of adversarial/legitimate label). If a signal's
values are almost constant, it cannot possibly discriminate classes --
that points to a computation bug (e.g. comparing against a fixed/wrong
reference) rather than a genuine null finding about semantic content.
"""

import sqlite3
import pandas as pd

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

print("Overall spread per signal (all rows, all roles pooled):")
print(df[SIGNAL_COLS].describe().T[["mean", "std", "min", "max"]])

print()
print("Coefficient of variation (std/mean) -- low value (<0.05) suggests")
print("near-constant output regardless of input, which would indicate a")
print("computation issue rather than a genuine null finding:")
for col in SIGNAL_COLS:
    m, s = df[col].mean(), df[col].std()
    cv = s / m if m != 0 else float("nan")
    flag = "  <-- SUSPICIOUSLY FLAT" if cv < 0.05 else ""
    print(f"  {col:16s} mean={m:.4f}  std={s:.4f}  cv={cv:.4f}{flag}")

print()
print("Sample of 10 raw rows (prompt_id, expected_drift, all signals) to eyeball:")
print(df[["prompt_id", "expected_drift"] + SIGNAL_COLS].sample(10, random_state=1).to_string(index=False))
