"""
baselines/diagnose_fpr.py

Pulls a few example rows for a given condition where expected_drift = 0
(legitimate prompts) from that condition's most recent run, so you can see
exactly what the detector scored/decided on benign input — the raw data
behind why FPR is showing 1.0.

Run:
    python -m baselines.diagnose_fpr
    python -m baselines.diagnose_fpr --condition B_prompt_contract
"""
from __future__ import annotations

import argparse
from pathlib import Path

from experiment.results_store import DEFAULT_DB_PATH, get_connection

QUERY = """
SELECT prompt_id, role, condition, expected_drift, drift_detected, blocked,
       decision, score, substr(response_excerpt, 1, 200) as excerpt
FROM experiment_results
WHERE condition = ?
  AND expected_drift = 0
  AND run_id = (
      SELECT er.run_id FROM experiment_results er
      JOIN experiment_runs runs ON runs.run_id = er.run_id
      WHERE er.condition = ?
      ORDER BY runs.started_at DESC LIMIT 1
  )
LIMIT 8
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect false-positive rows for one condition's latest run.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--condition", default="C_rmic_middleware")
    args = parser.parse_args()

    conn = get_connection(args.db_path)
    rows = conn.execute(QUERY, (args.condition, args.condition)).fetchall()
    conn.close()

    if not rows:
        print(f"No rows found for condition={args.condition!r}. Check the condition name.")
        return

    for r in rows:
        print("-" * 70)
        print(f"prompt_id:       {r['prompt_id']}")
        print(f"role:            {r['role']}")
        print(f"drift_detected:  {r['drift_detected']}")
        print(f"blocked:         {r['blocked']}")
        print(f"decision:        {r['decision']}")
        print(f"score:           {r['score']}")
        print(f"response_excerpt:{r['excerpt']}")
    print("-" * 70)


if __name__ == "__main__":
    main()