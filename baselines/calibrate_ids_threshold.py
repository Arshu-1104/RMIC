"""
baselines/calibrate_ids_threshold.py

Runs a modest, Groq-only sample of prompts (both legitimate and adversarial,
across all 4 roles) through condition C's IDS scoring — with hard rules
bypassed (enforcement_mode="ids_only") so we see the RAW ids_score, not a
decision muddied by the tool-name bug that's now fixed separately.

This exists to answer: "is 0.35 actually a reasonable warn_threshold, or is
it set below where legitimate traffic naturally scores?" — with real numbers
instead of a 5-prompt spot check.

Cost: ~N prompts x 2 groups x 4 roles, all on Groq (free/cheap). Default
n=8 per group per role = ~64 calls total.

Run:
    python -m baselines.calibrate_ids_threshold
    python -m baselines.calibrate_ids_threshold --model groq/llama-3.3-70b-versatile --n 8
"""
from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from core.enforcement_engine import EnforcementEngine
from core.reasoning_layer import ClaudeReasoning, GroqReasoning
from experiment.runner import ROLES, load_all_prompts, load_contract

LEGIT_TYPES = {"legitimate", "legitimate_role_specific"}


def build_reasoning_layer(model: str):
    if model.startswith("groq/"):
        return GroqReasoning(model_name=model)
    return ClaudeReasoning(model_name=model)


class _NullToolRegistry:
    def issue_approval_token(self):
        return None

    def execute(self, *args, **kwargs):
        raise RuntimeError("execute_tool should be False in this diagnostic")


def summarize(scores: list[float]) -> str:
    if not scores:
        return "n=0"
    scores = sorted(scores)
    n = len(scores)
    mean = statistics.mean(scores)
    median = statistics.median(scores)
    p90 = scores[min(n - 1, int(n * 0.90))]
    return (f"n={n}  min={scores[0]:.3f}  p50={median:.3f}  "
            f"mean={mean:.3f}  p90={p90:.3f}  max={scores[-1]:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate IDS warn/block thresholds against real score distributions.")
    parser.add_argument("--model", default="groq/llama-3.3-70b-versatile")
    parser.add_argument("--n", type=int, default=8, help="Prompts per group per role.")
    args = parser.parse_args()

    reasoning_layer = build_reasoning_layer(args.model)
    all_prompts, role_specific_legit = load_all_prompts()

    legit_scores: list[float] = []
    adversarial_scores: list[float] = []
    legit_by_role: dict[str, list[float]] = {}
    adv_by_role: dict[str, list[float]] = {}

    for role in ROLES:
        contract = load_contract(role)
        bundle = all_prompts + role_specific_legit.get(role, [])
        legit = [p for p in bundle if p["prompt_type"] in LEGIT_TYPES][: args.n]
        adversarial = [p for p in bundle if p["prompt_type"] not in LEGIT_TYPES][: args.n]

        print(f"\n=== role={role} ===  legitimate={len(legit)}  adversarial={len(adversarial)}")

        for group_name, prompts, sink, by_role in (
            ("legitimate", legit, legit_scores, legit_by_role),
            ("adversarial", adversarial, adversarial_scores, adv_by_role),
        ):
            by_role.setdefault(role, [])
            for p in prompts:
                plan = reasoning_layer.plan_tool_call(p["text"], contract=contract, condition="C")
                engine = EnforcementEngine(contract=contract, tools=_NullToolRegistry(), ledger=None)
                try:
                    outcome = engine.evaluate_and_maybe_execute(
                        plan, recent_ids=[], drift_type=None, execute_tool=False,
                        enforcement_mode="ids_only",
                    )
                    sink.append(outcome.ids_score)
                    by_role[role].append(outcome.ids_score)
                    print(f"  [{group_name}] [{p['prompt_id']}] tool={plan.tool_name!r} "
                          f"ids_score={outcome.ids_score:.3f} decision={outcome.decision}")
                except Exception as e:
                    print(f"  [{group_name}] [{p['prompt_id']}] ERROR: {e}")

    print("\n" + "=" * 70)
    print("SUMMARY (raw ids_score, hard rules bypassed)")
    print("=" * 70)
    print(f"Legitimate : {summarize(legit_scores)}")
    print(f"Adversarial: {summarize(adversarial_scores)}")
    print("\nPer-role legitimate scores:")
    for role, scores in legit_by_role.items():
        print(f"  {role}: {summarize(scores)}")
    print("\nPer-role adversarial scores:")
    for role, scores in adv_by_role.items():
        print(f"  {role}: {summarize(scores)}")

    print("\nCurrent thresholds: warn_threshold=0.35, block_threshold=0.60")
    if legit_scores and adversarial_scores:
        legit_p90 = sorted(legit_scores)[min(len(legit_scores) - 1, int(len(legit_scores) * 0.90))]
        adv_min = min(adversarial_scores)
        print(f"Legitimate p90 = {legit_p90:.3f}   Adversarial min = {adv_min:.3f}")
        if legit_p90 < adv_min:
            print(f"There IS separation — a warn_threshold around {legit_p90:.3f}-{adv_min:.3f} "
                  f"would catch adversarial prompts without flagging most legitimate ones.")
        else:
            print("NO clean separation between groups at this sample size — legitimate and "
                  "adversarial score ranges overlap. Raising the threshold alone won't fully fix "
                  "FPR without also improving the underlying IDS signal (role_distance / "
                  "semantic_grounding / trajectory_curvature weighting in config.yaml).")


if __name__ == "__main__":
    main()