"""Cluster bootstrap (C, C1, C2 vs B) from exported run_*.csv files.
Usage: python cluster_bootstrap_csv.py path/to/exports [--reps 5000] [--seed 1]
Resamples (role, prompt_id) clusters; rows de-duplicated by id; test runs (<=48 rows) and D/E excluded."""
import csv, glob, collections, random, sys, os, argparse
ap = argparse.ArgumentParser(); ap.add_argument("folder"); ap.add_argument("--reps", type=int, default=5000); ap.add_argument("--seed", type=int, default=1)
a = ap.parse_args()
TEST_RUNS = {"run_20260506_050231", "run_20260506_050933", "run_20260506_052102", "run_20260506_055628", "run_20260731_095107"}  # smoke tests
tf = lambda x: str(x).strip().lower() in ("1", "true", "t", "yes")
seen, runsize = {}, collections.Counter()
for f in sorted(glob.glob(os.path.join(a.folder, "run_*.csv"))):
    for r in csv.DictReader(open(f, encoding="utf8")):
        seen.setdefault(r["id"], r); runsize[r["run_id"]] += 1
cl = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0, 0]))
for r in seen.values():
    k = r["condition"].split("_")[0]
    if k not in ("B", "C", "C1", "C2") or r["run_id"] in TEST_RUNS:
        continue
    x = cl[(r["role"], r["prompt_id"])][k]
    if tf(r["expected_drift"]): x[0] += 1; x[1] += tf(r["blocked"])
    else: x[2] += 1; x[3] += tf(r["blocked"])
keys = [k for k in cl if "B" in cl[k]]
def stat(ks, c):
    s = [0] * 4
    for k in ks:
        v = cl[k].get(c)
        if v: s = [p + q for p, q in zip(s, v)]
    d = s[1] / s[0]; f = s[3] / s[2]; return d, f, (d + 1 - f) / 2
random.seed(a.seed)
for c in ("C", "C1", "C2"):
    o = [x - y for x, y in zip(stat(keys, c), stat(keys, "B"))]; bs = []
    for _ in range(a.reps):
        ks = [random.choice(keys) for _ in keys]; bs.append([x - y for x, y in zip(stat(ks, c), stat(ks, "B"))])
    print(c, "vs B:", " | ".join("%s %+.3f [%+.3f, %+.3f]" % (n, o[i], sorted(b[i] for b in bs)[int(.025 * a.reps)], sorted(b[i] for b in bs)[int(.975 * a.reps) - 1]) for i, n in enumerate(("DSR", "FPR", "BA"))))
