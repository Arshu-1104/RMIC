import sqlite3
import pandas as pd

DB_PATH = "results/experiment_results.db"
CONDITION = "C2_ids_only"

conn = sqlite3.connect(DB_PATH)
df = pd.read_sql_query(
    "SELECT role, response_excerpt FROM experiment_results WHERE condition = ? AND base_ids IS NOT NULL",
    conn, params=(CONDITION,)
)
conn.close()

df["excerpt_len"] = df["response_excerpt"].fillna("").str.len()

print(f"Total rows checked: {len(df)}")
print(f"Rows where excerpt_len == 240 (i.e. LIKELY truncated, was cut off at the limit):")
print(df[df["excerpt_len"] == 240].groupby("role").size())
print()
print(f"Rows where excerpt_len < 240 (i.e. full text captured, safe to reuse):")
print(df[df["excerpt_len"] < 240].groupby("role").size())
print()
print("Overall excerpt length stats:")
print(df["excerpt_len"].describe())
