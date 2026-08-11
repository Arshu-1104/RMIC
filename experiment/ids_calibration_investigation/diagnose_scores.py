"""
Diagnostic: why is DSR/FPR separation collapsing when pooled?

Checks:
1. Mean base_ids for adversarial vs legitimate, per role (sanity check
   on score direction).
2. Same breakdown, but split by run_id -- to see if some runs behave
   very differently from others (e.g. pre- vs post- bugfix).
3. Same breakdown, split by model, if a model column exists.
"""

import sqlite3
import pandas as pd

DB_PATH = "results/experiment_results.db"
CONDITION = "C2_ids_only"

conn = sqlite3.connect(DB_PATH)

# Check what columns actually exist so we don't guess wrong on model column name
cols = pd.read_sql_query("PRAGMA table_info(experiment_results)", conn)
print("Available columns:")
print(cols["name"].tolist())
print()

df = pd.read_sql_query(
    f"SELECT * FROM experiment_results WHERE condition = ? AND base_ids IS NOT NULL",
    conn, params=(CONDITION,)
)
conn.close()

print("=" * 70)
print("1) Mean base_ids by role and expected_drift (adversarial should be HIGHER)")
print("=" * 70)
print(df.groupby(["role", "expected_drift"])["base_ids"].agg(["mean", "median", "count"]))

print()
print("=" * 70)
print("2) Mean base_ids by run_id and expected_drift")
print("=" * 70)
print(df.groupby(["run_id", "expected_drift"])["base_ids"].agg(["mean", "count"]))

model_col = None
for candidate in ["model", "model_name", "llm", "llm_model"]:
    if candidate in df.columns:
        model_col = candidate
        break

if model_col:
    print()
    print("=" * 70)
    print(f"3) Mean base_ids by {model_col} and expected_drift")
    print("=" * 70)
    print(df.groupby([model_col, "expected_drift"])["base_ids"].agg(["mean", "count"]))
else:
    print()
    print("No model column found -- checked: model, model_name, llm, llm_model")
    print("(see 'Available columns' above to find the right one if named differently)")
