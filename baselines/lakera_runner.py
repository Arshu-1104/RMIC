"""
baselines/lakera_runner.py

Runs the SAME prompt set used by experiment/runner.py (prompts/*.json, all
4 roles) through Lakera Guard's /v2/guard endpoint, and writes results into
the same SQLite table (experiment_results) under condition="D_lakera_guard".

Because it lands in the same table with the same run_id/condition schema as
B_prompt_contract / C_rmic_middleware / C1 / C2, experiment/metrics.py and
the xlsx export (condition_summary sheet) will show it side-by-side with
RMIC-Guard automatically — no separate report needed.

Setup:
    pip install httpx python-dotenv   (both already in requirements.txt)
    Add to .env:
        LAKERA_GUARD_API_KEY=lakera_guard_xxx...

Run:
    python -m baselines.lakera_runner --test     # 3 prompts/role, quick check
    python -m baselines.lakera_runner             # full run, all prompts x 4 roles

Notes / fairness caveats (worth stating explicitly in your write-up):
  - Lakera Guard has no first-class concept of a "role contract." We hand it
    the same role_description / allowed_actions / forbidden_actions as a
    system message, which is the closest fair analogue to condition B
    (prompt-based framing) — NOT to condition C's structural enforcement.
  - Lakera screens a single input/output pair per call; it does not track
    state across a session the way RMIC-Guard's IDS trajectory metrics do.
    This is expected to matter most on slow-onset drift prompt types.
  - You need a Lakera project with a configured policy (not just the
    strict default policy) for flagging rates to be meaningful — see the
    account-setup notes below.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

from experiment.runner import ROLES, load_all_prompts, load_contract, utc_now_iso, make_run_id
from experiment.results_store import (
    DEFAULT_DB_PATH, complete_run, create_run, export_run_to_csv,
    export_run_to_json, export_run_summary_excel, get_connection, init_db, insert_result,
)

CONDITION = "D_lakera_guard"
LAKERA_URL = "https://api.lakera.ai/v2/guard"


def build_system_context(contract) -> str:
    """Give Lakera the same role framing the LLM conditions receive."""
    lines = [
        f"You are acting as: {contract.role_name} ({contract.sector}).",
        contract.role_description,
    ]
    if contract.allowed_actions:
        lines.append("Allowed actions: " + ", ".join(contract.allowed_actions))
    if contract.forbidden_actions:
        lines.append("Forbidden actions: " + ", ".join(contract.forbidden_actions))
    return "\n".join(lines)


def call_lakera(api_key: str, system_context: str, user_text: str, timeout: float = 15.0) -> dict[str, Any]:
    resp = httpx.post(
        LAKERA_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "messages": [
                {"role": "system", "content": system_context},
                {"role": "user", "content": user_text},
            ],
            "breakdown": True,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def run_baseline(db_path: Path, test_mode: bool = False) -> tuple[str, int]:
    load_dotenv(Path(".env"))
    load_dotenv()
    api_key = (os.environ.get("LAKERA_GUARD_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("LAKERA_GUARD_API_KEY not set. Add it to .env — see baselines/README.md")

    all_prompts, role_specific_legit = load_all_prompts()
    if not all_prompts:
        raise RuntimeError("No prompts loaded. Check prompts/ folder.")

    run_id = make_run_id() + "_lakera"
    conn = get_connection(db_path)
    init_db(conn)
    create_run(conn, run_id=run_id, mode="test" if test_mode else "full",
               model="lakera-guard-v2", manifest_hash=None)

    inserted = 0
    errors = 0

    try:
        for role in ROLES:
            print(f"[Lakera] Loading contract for: {role}")
            try:
                contract = load_contract(role)
            except Exception as e:
                print(f"[Lakera] ERROR loading contract for {role}: {e}")
                errors += 1
                continue
            system_context = build_system_context(contract)

            prompt_bundle = all_prompts + role_specific_legit.get(role, [])
            prompt_specs = prompt_bundle[:3] if test_mode else prompt_bundle
            prompt_specs = sorted(prompt_specs, key=lambda p: p["prompt_id"])

            for prompt in prompt_specs:
                prompt_type = prompt["prompt_type"]
                expected_drift = 0 if prompt_type in {"legitimate", "legitimate_role_specific"} else 1

                t0 = time.perf_counter()
                try:
                    result = call_lakera(api_key, system_context, prompt["text"])
                except Exception as e:
                    print(f"  [ERROR] {role}/{prompt['prompt_id']}: {e}")
                    errors += 1
                    continue

                flagged = bool(result.get("flagged", False))
                breakdown = result.get("breakdown") or result.get("payload") or []
                excerpt = str(breakdown)[:240]
                decision = "BLOCK" if flagged else "ALLOW"
                blocked = 1 if flagged else 0
                drift_detected = 1 if flagged else 0

                latency_ms = int((time.perf_counter() - t0) * 1000)
                row = {
                    "run_id": run_id,
                    "provider": "lakera",
                    "prompt_id": prompt["prompt_id"],
                    "prompt_type": prompt_type,
                    "detected_drift_type": prompt_type if drift_detected else None,
                    "role": role,
                    "condition": CONDITION,
                    "expected_drift": expected_drift,
                    "drift_detected": drift_detected,
                    "blocked": blocked,
                    "score": float(1.0 if flagged else 0.0),
                    "latency_ms": latency_ms,
                    "decision": decision,
                    "response_excerpt": excerpt,
                    "created_at": utc_now_iso(),
                }
                insert_result(conn, row)
                inserted += 1
                print(f"  [{role}] [{prompt['prompt_id']}] {decision} {latency_ms}ms")
                time.sleep(0.05 if test_mode else 0.3)

        conn.commit()
        export_dir = db_path.parent / "exports"
        csv_path = export_run_to_csv(conn, run_id, export_dir)
        json_path = export_run_to_json(conn, run_id, export_dir)
        xlsx_path = export_run_summary_excel(conn, run_id, export_dir)
        print(f"\n[Lakera] Complete. Inserted: {inserted}  Errors: {errors}")
        print(f"[Lakera] CSV:  {csv_path}")
        print(f"[Lakera] JSON: {json_path}")
        print(f"[Lakera] XLSX: {xlsx_path}")
    finally:
        complete_run(conn, run_id=run_id)
        conn.close()

    return run_id, inserted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the RMIC-Guard prompt set through Lakera Guard.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--test", action="store_true", help="Test mode: 3 prompts/role only.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_id, inserted = run_baseline(db_path=args.db_path, test_mode=args.test)
    print(f"\nrun_id={run_id}\nrows_inserted={inserted}\ndb_path={args.db_path}")


if __name__ == "__main__":
    main()