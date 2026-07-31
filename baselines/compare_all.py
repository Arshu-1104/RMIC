"""
baselines/compare_all.py

RMIC-Guard's own conditions (B/C/C1/C2) and the two baselines (D_lakera_guard,
E_nemo_guardrails) each get their own run_id when you run their respective
scripts. export_run_summary_excel() only summarizes ONE run_id at a time, so
there's no single view of all six conditions side by side out of the box.

This script fixes that: it queries the whole database, groups by `condition`
regardless of run_id, and prints + exports one merged comparison table —
the actual "final" benchmark result for your report.

Run (after you've done the full, non---test runs of everything):
    python -m baselines.compare_all
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from experiment.results_store import DEFAULT_DB_PATH, get_connection

QUERY = """
SELECT
    condition,
    COUNT(*) AS n,
    SUM(CASE WHEN expected_drift = 1 THEN 1 ELSE 0 END) AS n_adversarial,
    SUM(CASE WHEN expected_drift = 0 THEN 1 ELSE 0 END) AS n_benign,
    SUM(CASE WHEN expected_drift = 1 AND drift_detected = 1 THEN 1 ELSE 0 END) AS tp,
    SUM(CASE WHEN expected_drift = 1 AND drift_detected = 0 THEN 1 ELSE 0 END) AS fn,
    SUM(CASE WHEN expected_drift = 0 AND drift_detected = 1 THEN 1 ELSE 0 END) AS fp,
    SUM(CASE WHEN expected_drift = 0 AND drift_detected = 0 THEN 1 ELSE 0 END) AS tn,
    ROUND(AVG(latency_ms), 1) AS avg_latency_ms
FROM experiment_results
GROUP BY condition
ORDER BY condition
"""


def compute_row(r) -> dict:
    tp, fn, fp, tn = r["tp"] or 0, r["fn"] or 0, r["fp"] or 0, r["tn"] or 0
    n_adv = r["n_adversarial"] or 0
    n_ben = r["n_benign"] or 0

    dsr = (tp / n_adv) if n_adv else None      # Drift/Detection Success Rate
    ddr = dsr                                    # alias, same computation here
    fpr = (fp / n_ben) if n_ben else None       # False Positive Rate on benign
    precision = (tp / (tp + fp)) if (tp + fp) else None
    recall = dsr

    return {
        "condition": r["condition"],
        "n_total": r["n"],
        "n_adversarial": n_adv,
        "n_benign": n_ben,
        "DSR": round(dsr, 4) if dsr is not None else "n/a",
        "FPR": round(fpr, 4) if fpr is not None else "n/a",
        "precision": round(precision, 4) if precision is not None else "n/a",
        "recall": round(recall, 4) if recall is not None else "n/a",
        "avg_latency_ms": r["avg_latency_ms"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge all conditions across all run_ids into one comparison.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=Path("results/exports/condition_comparison_all.csv"))
    args = parser.parse_args()

    conn = get_connection(args.db_path)
    rows = [compute_row(r) for r in conn.execute(QUERY).fetchall()]
    conn.close()

    if not rows:
        print("No rows found in the database. Run the experiments first.")
        return

    headers = list(rows[0].keys())
    col_widths = [max(len(h), *(len(str(r[h])) for r in rows)) for h in headers]

    def fmt_row(values):
        return "  ".join(str(v).ljust(w) for v, w in zip(values, col_widths))

    print(fmt_row(headers))
    print("  ".join("-" * w for w in col_widths))
    for r in rows:
        print(fmt_row(r.values()))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved: {args.out}")


if __name__ == "__main__":
    main()