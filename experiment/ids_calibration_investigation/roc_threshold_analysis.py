"""
ROC / AUC / threshold-sensitivity analysis for RMIC-Guard's IDS scoring.

Answers the reviewer question: "if we sweep the block threshold, what
DSR do we get at what FPR cost, per agent role?" -- using the raw
base_ids scores already stored in experiment_results.db (condition C
or C2), rather than requiring a new experiment run.

Usage:
    python roc_threshold_analysis.py

Outputs:
    - results/roc_per_role.csv        (threshold sweep table, per role)
    - results/roc_summary.csv         (AUC + best operating point per role)
    - results/roc_curves.png          (one ROC curve per role, overlaid)
"""

import sqlite3
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

DB_PATH = "results/experiment_results.db"

# Which condition to pull scores from. C_rmic_middleware includes both
# passes; C2_ids_only isolates the IDS signal from hard-rule blocking.
# The paper should be explicit about which one it's reporting -- C2 is
# the cleaner choice for a pure IDS ROC curve since Pass 1 can't
# contaminate the score.
CONDITION = "C2_ids_only"

THRESHOLDS = np.round(np.arange(0.05, 1.00, 0.05), 2)


def load_scores(conn, condition):
    query = """
        SELECT role, base_ids, expected_drift
        FROM experiment_results
        WHERE condition = ?
          AND base_ids IS NOT NULL
    """
    df = pd.read_sql_query(query, conn, params=(condition,))
    if df.empty:
        raise ValueError(
            f"No rows found for condition='{condition}'. "
            "Check the condition string matches your DB exactly."
        )
    return df


def sweep_thresholds(df, thresholds):
    """
    For each role and each threshold, compute:
        DSR (a.k.a. TPR) = adversarial prompts blocked / total adversarial
        FPR              = legitimate prompts blocked / total legitimate
    A prompt is "blocked" at threshold t if base_ids >= t.
    """
    rows = []
    for role, group in df.groupby("role"):
        adv = group[group["expected_drift"] == 1]
        leg = group[group["expected_drift"] == 0]

        n_adv = len(adv)
        n_leg = len(leg)

        if n_adv == 0 or n_leg == 0:
            print(f"WARNING: role '{role}' has n_adv={n_adv}, n_leg={n_leg} "
                  f"-- skipping (need both classes to compute DSR/FPR).")
            continue

        for t in thresholds:
            dsr = (adv["base_ids"] >= t).sum() / n_adv
            fpr = (leg["base_ids"] >= t).sum() / n_leg
            rows.append({
                "role": role,
                "threshold": t,
                "DSR": dsr,
                "FPR": fpr,
                "n_adv": n_adv,
                "n_leg": n_leg,
            })
    return pd.DataFrame(rows)


def compute_auc_per_role(sweep_df):
    """
    Trapezoidal AUC over (FPR, DSR) points, sorted by FPR ascending.
    Also reports the best operating point per role: the threshold that
    maximizes DSR subject to FPR <= 0.05, per Reviewer C's request.
    """
    summary = []
    for role, group in sweep_df.groupby("role"):
        g = group.sort_values("FPR")
        # Anchor the curve at (0,0) and (1,1) for a well-formed AUC.
        fpr_vals = np.concatenate(([0.0], g["FPR"].values, [1.0]))
        dsr_vals = np.concatenate(([0.0], g["DSR"].values, [1.0]))
        trapz_fn = getattr(np, "trapezoid", None) or np.trapz
        auc = trapz_fn(dsr_vals, fpr_vals)

        constrained = group[group["FPR"] <= 0.05]
        if not constrained.empty:
            best = constrained.loc[constrained["DSR"].idxmax()]
            best_threshold = best["threshold"]
            best_dsr = best["DSR"]
            best_fpr = best["FPR"]
        else:
            best_threshold = None
            best_dsr = None
            best_fpr = None
            print(f"NOTE: role '{role}' has no threshold achieving FPR <= 0.05 "
                  f"in the tested grid -- consider finer-grained thresholds "
                  f"near the low-FPR region for this role.")

        summary.append({
            "role": role,
            "AUC": round(auc, 4),
            "best_threshold_at_FPR<=0.05": best_threshold,
            "DSR_at_best_threshold": best_dsr,
            "FPR_at_best_threshold": best_fpr,
        })
    return pd.DataFrame(summary)


def plot_roc_curves(sweep_df, out_path):
    plt.figure(figsize=(7, 6))
    for role, group in sweep_df.groupby("role"):
        g = group.sort_values("FPR")
        plt.plot(g["FPR"], g["DSR"], marker="o", label=role, linewidth=1.5)

    plt.plot([0, 1], [0, 1], linestyle="--", color="gray", linewidth=1,
              label="Chance")
    plt.axvline(0.05, linestyle=":", color="red", linewidth=1,
                label="FPR = 0.05 target")
    plt.xlabel("False Positive Rate (FPR)")
    plt.ylabel("Drift Suppression Rate / TPR (DSR)")
    plt.title("RMIC-Guard IDS: DSR vs. FPR across thresholds, per agent role")
    plt.legend(loc="lower right", fontsize=8)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    print(f"Saved ROC plot to {out_path}")


def main():
    conn = sqlite3.connect(DB_PATH)
    df = load_scores(conn, CONDITION)
    conn.close()

    print(f"Loaded {len(df)} rows for condition='{CONDITION}'")
    print(df.groupby("role")["expected_drift"].value_counts())

    sweep_df = sweep_thresholds(df, THRESHOLDS)
    sweep_df.to_csv("results/roc_per_role.csv", index=False)
    print("Saved threshold sweep table to results/roc_per_role.csv")

    summary_df = compute_auc_per_role(sweep_df)
    summary_df.to_csv("results/roc_summary.csv", index=False)
    print("\nAUC + best operating point per role:")
    print(summary_df.to_string(index=False))

    plot_roc_curves(sweep_df, "results/roc_curves.png")


if __name__ == "__main__":
    main()
