"""
baselines/agentdojo_runner.py

Runs the SAME RMIC-Guard identity-drift prompt set used by the existing
Lakera and NeMo baselines through AgentDojo's local
TransformersBasedPIDetector.

Results are written into the SAME SQLite experiment_results table under:

    condition = "F_agentdojo"

No external API key is required. The detector runs locally using the
protectai/deberta-v3-base-prompt-injection-v2 model.

Test:
    python -m baselines.agentdojo_runner --test

Full run:
    python -m baselines.agentdojo_runner
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

from agentdojo.agent_pipeline import TransformersBasedPIDetector

from experiment.runner import (
    ROLES,
    load_all_prompts,
    load_contract,
    utc_now_iso,
    make_run_id,
)

from experiment.results_store import (
    DEFAULT_DB_PATH,
    complete_run,
    create_run,
    export_run_to_csv,
    export_run_to_json,
    export_run_summary_excel,
    get_connection,
    init_db,
    insert_result,
)


CONDITION = "F_agentdojo"


def run_baseline(
    db_path: Path,
    test_mode: bool = False,
) -> tuple[str, int]:

    print("[AgentDojo] Initializing local prompt-injection detector...")

    detector = TransformersBasedPIDetector()

    print("[AgentDojo] Detector initialized.")

    all_prompts, role_specific_legit = load_all_prompts()

    if not all_prompts:
        raise RuntimeError(
            "No prompts loaded. Check the prompts/ folder."
        )

    run_id = make_run_id() + "_agentdojo"

    conn = get_connection(db_path)
    init_db(conn)

    create_run(
        conn,
        run_id=run_id,
        mode="test" if test_mode else "full",
        model="agentdojo-transformers-pi-detector",
        manifest_hash=None,
    )

    inserted = 0
    errors = 0

    try:

        for role in ROLES:

            print(f"[AgentDojo] Loading contract for: {role}")

            try:
                load_contract(role)
            except Exception as e:
                print(
                    f"[AgentDojo] ERROR loading contract for {role}: {e}"
                )
                errors += 1
                continue

            prompt_bundle = (
                all_prompts
                + role_specific_legit.get(role, [])
            )

            if test_mode:
                prompt_specs = prompt_bundle[:3]
            else:
                prompt_specs = prompt_bundle

            prompt_specs = sorted(
                prompt_specs,
                key=lambda p: p["prompt_id"],
            )

            for prompt in prompt_specs:

                prompt_type = prompt["prompt_type"]

                expected_drift = (
                    0
                    if prompt_type
                    in {
                        "legitimate",
                        "legitimate_role_specific",
                    }
                    else 1
                )

                t0 = time.perf_counter()

                try:
                    detected, score = detector.detect(
                        prompt["text"]
                    )

                except Exception as e:
                    print(
                        f"  [ERROR] "
                        f"{role}/{prompt['prompt_id']}: {e}"
                    )
                    errors += 1
                    continue

                latency_ms = int(
                    (time.perf_counter() - t0) * 1000
                )

                drift_detected = 1 if detected else 0
                blocked = drift_detected

                decision = (
                    "BLOCK"
                    if drift_detected
                    else "ALLOW"
                )

                detected_drift_type = (
                    prompt_type
                    if drift_detected
                    else None
                )

                row = {
                    "run_id": run_id,
                    "provider": "agentdojo",
                    "prompt_id": prompt["prompt_id"],
                    "prompt_type": prompt_type,
                    "detected_drift_type": detected_drift_type,
                    "role": role,
                    "condition": CONDITION,
                    "expected_drift": expected_drift,
                    "drift_detected": drift_detected,
                    "blocked": blocked,
                    "score": float(score),
                    "latency_ms": latency_ms,
                    "decision": decision,
                    "response_excerpt": (
                        f"AgentDojo detector score={score:.6f}"
                    ),
                    "created_at": utc_now_iso(),
                }

                insert_result(conn, row)

                inserted += 1

                print(
                    f"  [{role}] "
                    f"[{prompt['prompt_id']}] "
                    f"{decision} "
                    f"score={score:.6f} "
                    f"{latency_ms}ms"
                )

                time.sleep(
                    0.05 if test_mode else 0.1
                )

        conn.commit()

        export_dir = db_path.parent / "exports"

        csv_path = export_run_to_csv(
            conn,
            run_id,
            export_dir,
        )

        json_path = export_run_to_json(
            conn,
            run_id,
            export_dir,
        )

        xlsx_path = export_run_summary_excel(
            conn,
            run_id,
            export_dir,
        )

        print(
            f"\n[AgentDojo] Complete. "
            f"Inserted: {inserted}  "
            f"Errors: {errors}"
        )

        print(f"[AgentDojo] CSV:  {csv_path}")
        print(f"[AgentDojo] JSON: {json_path}")
        print(f"[AgentDojo] XLSX: {xlsx_path}")

    finally:

        complete_run(
            conn,
            run_id=run_id,
        )

        conn.close()

    return run_id, inserted


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Run the RMIC-Guard prompt set through "
            "AgentDojo's local prompt-injection detector."
        )
    )

    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help=(
            "Test mode: 3 prompts/role only."
        ),
    )

    return parser.parse_args()


def main() -> None:

    args = parse_args()

    run_id, inserted = run_baseline(
        db_path=args.db_path,
        test_mode=args.test,
    )

    print(
        f"\nrun_id={run_id}"
        f"\nrows_inserted={inserted}"
        f"\ndb_path={args.db_path}"
    )


if __name__ == "__main__":
    main()