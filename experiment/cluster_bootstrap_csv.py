"""Paired cluster bootstrap, C vs B, for the nine runs that make up Table III.

    python cluster_bootstrap_csv.py experiment/exports [--reps 2000] [--seed 42]

A pair is the same prompt (role, prompt_id) in the same run under B and C. Whole prompts
(role, prompt_id) are resampled as clusters, because a prompt appears in several runs.
Outcome = BLOCK decision. Expected output (seed 42):
  attacks   684 pairs / 100 prompts: +31.7 pp [+27.6, +35.7]  251:34
  legit     416 pairs /  60 prompts: +44.5 pp [+40.7, +48.3]  185:0
  balanced accuracy difference: -6.4 pp [-9.2, -3.7]
"""
import argparse, collections, csv, math, os, random

TABLE3_RUNS = ["run_20260506_071804", "run_20260506_113730", "run_20260730_145056", "run_20260730_165245",
               "run_20260731_200802", "run_20260506_085837", "run_20260506_101226"]
ap = argparse.ArgumentParser(); ap.add_argument("folder"); ap.add_argument("--reps", type=int, default=2000)
ap.add_argument("--seed", type=int, default=42); a = ap.parse_args()
tf = lambda x: str(x).strip().lower() in ("1", "true", "t", "yes")

by = {}
for rid in TABLE3_RUNS:
    for r in csv.DictReader(open(os.path.join(a.folder, rid + ".csv"), encoding="utf8")):
        if r["condition"] in ("B_prompt_contract", "C_rmic_middleware"):
            by.setdefault((rid, r["role"], r["prompt_id"], tf(r["expected_drift"])), {})[r["condition"]] = int(tf(r["blocked"]))
pairs = [(k, v["B_prompt_contract"], v["C_rmic_middleware"]) for k, v in by.items() if len(v) == 2]
cl = collections.defaultdict(list)
for k, b, c in pairs:
    cl[(k[1], k[2])].append((k[3], b, c))
keys = list(cl)

def diff(ks, attack):
    x = [(b, c) for kk in ks for e, b, c in cl[kk] if e == attack]
    return sum(c - b for b, c in x) / len(x)

def ci(f, pool=None):
    pool = pool or keys
    rng = random.Random(a.seed)  # same seed for every statistic
    v = sorted(f([rng.choice(pool) for _ in pool]) for _ in range(a.reps)); return v[int(.025 * a.reps) - 1], v[int(.975 * a.reps) - 1]
for name, att in (("attacks", True), ("legit  ", False)):
    x = [(b, c) for e, b, c in (t for kk in keys for t in cl[kk]) if e == att]
    n10 = sum(1 for b, c in x if c and not b); n01 = sum(1 for b, c in x if b and not c); m = n10 + n01
    p = min(1.0, 2 * sum(math.comb(m, i) for i in range(min(n10, n01) + 1)) / 2 ** m)
    pool = list(dict.fromkeys((k[1], k[2]) for k, _, _ in pairs if k[3] == att))  # prompts of this type
    lo, hi = ci(lambda ks: diff(ks, att), pool)
    print("%s %d pairs / %d prompts: %+.1f pp [%+.1f, %+.1f]  %d:%d  McNemar p=%.2g" %
          (name, len(x), len({kk for kk in keys if any(e == att for e, _, _ in cl[kk])}), 100 * diff(keys, att), 100 * lo, 100 * hi, n10, n01, p))
ba = lambda ks: (diff(ks, True) - diff(ks, False)) / 2
lo, hi = ci(ba)
print("balanced accuracy difference: %+.1f pp [%+.1f, %+.1f]" % (100 * ba(keys), 100 * lo, 100 * hi))
