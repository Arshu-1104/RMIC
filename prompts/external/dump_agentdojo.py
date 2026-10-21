"""Dump AgentDojo's banking tasks (benchmark v1.2.2) with their ground-truth tool calls.

Run with an environment where AgentDojo (commit 089ed468, package 0.1.35) is installed:

    python prompts/external/dump_agentdojo.py prompts/external/raw/agentdojo_banking_v1.2.2.json

Uses AgentDojo's own loader and ground_truth() so the calls are exactly the benchmark's.
"""

from __future__ import annotations

import json
import sys
from importlib.metadata import version

from agentdojo.task_suite.load_suites import get_suite

BENCHMARK_VERSION = "v1.2.2"


def _calls(task, env) -> list[dict]:
    return [{"function": c.function, "args": dict(c.args)} for c in task.ground_truth(env)]


def main(out_path: str) -> None:
    suite = get_suite(BENCHMARK_VERSION, "banking")
    env = suite.load_and_inject_default_environment(suite.get_injection_vector_defaults())
    out = {
        "source": "AgentDojo",
        "package_version": version("agentdojo"),
        "benchmark_version": BENCHMARK_VERSION,
        "suite": "banking",
        "user_tasks": [
            {"id": tid, "prompt": t.PROMPT, "ground_truth": _calls(t, env.model_copy(deep=True))}
            for tid, t in suite.user_tasks.items()
        ],
        "injection_tasks": [
            {"id": tid, "goal": t.GOAL, "ground_truth": _calls(t, env.model_copy(deep=True))}
            for tid, t in suite.injection_tasks.items()
        ],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False, default=str)
        f.write("\n")
    print(f"user_tasks={len(out['user_tasks'])} injection_tasks={len(out['injection_tasks'])}")


if __name__ == "__main__":
    main(sys.argv[1])
