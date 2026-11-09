"""
Cluster-bootstrap confidence intervals for the original experiment (condition C vs B).

Why: each prompt was evaluated under several model configurations, so the
evaluations are not independent. This script resamples whole PROMPTS (a
prompt = role + prompt_id, with all of its evaluations in every condition)
instead of single evaluations, which gives honest (wider) intervals.

Usage (from the repo root, with your results database):
    python experiment/cluster_bootstrap.py --db results/experiment_results.db
Options:
    --flag blocked|detected|either   which column counts as "flagged" (default: blocked)
    --reps 10000

FIRST check that the printed point estimates match the paper (Table III):
    B: 437/799 adversarial, 196/480 legitimate; C: 639/785 and 375/476.
If they do not, try --flag either (or --flag detected).
"""
import argparse
import sqlite3
from collections import defaultdict

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--db", default="results/experiment_results.db")
ap.add_argument("--flag", choices=["blocked", "detected", "either"], default="blocked")
ap.add_argument("--reps", type=int, default=10000)
ap.add_argument("--seed", type=int, default=0)
args = ap.parse_args()

conn = sqlite3.connect(args.db)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    """
    SELECT e.condition, e.role, e.prompt_id, e.expected_drift,
           e.blocked, e.drift_detected
    FROM experiment_results e
    JOIN experiment_runs r ON r.run_id = e.run_id
    WHERE r.mode = 'full' AND e.condition IN ('B', 'C')
    """
).fetchall()
conn.close()
if not rows:
    raise SystemExit("No rows found. Check the database path and the condition names (B, C).")


def flagged(r):
    b, d = int(r["blocked"] or 0), int(r["drift_detected"] or 0)
    return {"blocked": b, "detected": d, "either": int(b or d)}[args.flag]


# cluster = (role, prompt_id); per cluster keep [adv_flag, adv_n, leg_flag, leg_n] for B and C
clusters = defaultdict(lambda: {"B": np.zeros(4), "C": np.zeros(4)})
for r in rows:
    key = (r["role"], r["prompt_id"])
    v = clusters[key][r["condition"]]
    if int(r["expected_drift"]) == 1:
        v[0] += flagged(r); v[1] += 1
    else:
        v[2] += flagged(r); v[3] += 1

keys = list(clusters)
B = np.array([clusters[k]["B"] for k in keys])
C = np.array([clusters[k]["C"] for k in keys])
print(f"{len(keys)} prompts (clusters), {len(rows)} evaluations\n")


def stats(Bs, Cs):
    out = {}
    for name, M in (("B", Bs), ("C", Cs)):
        a, an, l, ln = M.sum(0)
        out[name] = (a / an, l / ln)
    dsr = out["C"][0] - out["B"][0]
    fpr = out["C"][1] - out["B"][1]
    ba = ((out["C"][0] + 1 - out["C"][1]) - (out["B"][0] + 1 - out["B"][1])) / 2
    return dsr, fpr, ba


Bt, Ct = B.sum(0), C.sum(0)
print(f"B: adversarial {int(Bt[0])}/{int(Bt[1])}, legitimate {int(Bt[2])}/{int(Bt[3])}")
print(f"C: adversarial {int(Ct[0])}/{int(Ct[1])}, legitimate {int(Ct[2])}/{int(Ct[3])}\n")

point = stats(B, C)
rng = np.random.default_rng(args.seed)
n = len(keys)
boot = np.empty((args.reps, 3))
for i in range(args.reps):
    idx = rng.integers(0, n, n)
    boot[i] = stats(B[idx], C[idx])
lo, hi = np.percentile(boot, [2.5, 97.5], axis=0)
for j, name in enumerate(["DSR difference (C - B)", "FPR difference (C - B)", "Balanced-accuracy difference (C - B)"]):
    print(f"{name}: {point[j]:+.3f}  (95% cluster-bootstrap CI {lo[j]:+.3f} to {hi[j]:+.3f})")
