"""
IBM watsonx Orchestrate pilot — local demonstration.

Simulates the full pilot execution flow entirely locally, using the exact
same repository components ibm_pilot/rmic_guard_tool.py and
ibm_pilot/agent_example.py already wire together:

    User Request
      -> (simulated) IBM watsonx Orchestrate Agent   [core.reasoning_layer.ReasoningLayer]
      -> RMIC Guard Tool                              [ibm_pilot.rmic_guard_tool.RMICGuardTool]
      -> Existing Enforcement Engine                  [core.enforcement_engine.EnforcementEngine]
      -> Machine-Checkable Identity Contract          [core.contract_loader.RMICContract]
      -> Decision -> ALLOW (execute stub business tool) | BLOCK (reject)

No IBM SDK is required to run this file. It stands in for the Orchestrate
agent's own planning step using the repository's existing
core.reasoning_layer.ReasoningLayer — the same class the repository's own
top-level demo.py already uses — so tool_name/arguments below are real
model output, not hardcoded, and the four required scenarios can be
demonstrated without a live Orchestrate instance.

Run from the repository root (needs ANTHROPIC_API_KEY or GROQ_API_KEY set,
exactly like the repository's own demo.py):
    python ibm_pilot/demo.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from anthropic import APIConnectionError, APIStatusError, AuthenticationError
from dotenv import load_dotenv

from core.reasoning_layer import PlannedToolCall, ReasoningLayer

from ibm_pilot import config
from ibm_pilot.rmic_guard_tool import IBMAgentRequest, IBMToolResponse, RMICGuardTool

ROOT = config.REPO_ROOT


def _is_insufficient_credits_error(exc: BaseException) -> bool:
    """Same detection the repository's top-level demo.py uses, copied
    verbatim so this file gives the same actionable error message without
    importing a private helper from another script."""
    msg = str(exc).lower()
    if "credit balance" in msg or ("too low" in msg and "api" in msg):
        return True
    if isinstance(exc, APIStatusError) and exc.body is not None and isinstance(exc.body, dict):
        err = exc.body.get("error")
        if isinstance(err, dict):
            inner = str(err.get("message", "")).lower()
            return "credit" in inner and "balance" in inner
    return False


def _print_header(text: str) -> None:
    print("=" * 70)
    print(text)
    print("=" * 70)


def _print_scenario_result(
    label: str,
    prompt: str,
    expected: str,
    plan: PlannedToolCall,
    response: IBMToolResponse,
) -> None:
    match = "MATCH" if response.decision == expected else "MISMATCH"
    print(f"--- {label} ---")
    print(f"Prompt:            {prompt}")
    print(f"Planned tool call: {plan.tool_name}  args={plan.arguments}")
    print(f"Expected:          {expected}")
    print(f"Actual decision:   {response.decision}  ({match})")
    print(f"Reason:            {response.reason}")
    print(f"IDS score:         {response.ids_score:.4f}")
    if response.hard_rule_violation:
        print(f"Hard-rule hit:     {response.hard_rule_violation}")
    print()


def main() -> None:
    load_dotenv(ROOT / ".env")
    load_dotenv()

    _print_header("RMIC-Guard x IBM watsonx Orchestrate — local pilot demo")
    print(f"Contract:         {config.DEFAULT_CONTRACT_PATH.relative_to(ROOT)}")
    print(f"Audit log:        {config.AUDIT_LOG_PATH.relative_to(ROOT)}")
    print(f"Enforcement mode: {config.ENFORCEMENT_MODE}")
    print()

    # Stands in for the IBM watsonx Orchestrate agent's own planning step.
    # Reuses core.reasoning_layer.ReasoningLayer exactly as the repository's
    # own demo.py does — tool_name/arguments are real model output.
    reasoning = ReasoningLayer()

    # Reuses ibm_pilot.rmic_guard_tool.RMICGuardTool, which itself reuses
    # core.contract_loader.load_contract, core.audit_ledger.AuditLedger, and
    # core.enforcement_engine.EnforcementEngine exactly as constructed there.
    guard_tool = RMICGuardTool()

    results: list[tuple[str, str, str]] = []  # (label, expected, actual)

    for scenario in config.DEMO_SCENARIOS:
        plan = reasoning.plan_tool_call(
            scenario.prompt,
            contract=guard_tool.contract,
            condition="C",
        )

        request = IBMAgentRequest(
            user_message=scenario.prompt,
            tool_name=plan.tool_name,
            arguments=plan.arguments,
            data_categories_accessed=plan.data_categories_accessed,
        )
        response = guard_tool.handle_request(request, execute_tool=True)

        _print_scenario_result(
            scenario.label,
            scenario.prompt,
            scenario.expected_decision,
            plan,
            response,
        )
        results.append((scenario.label, scenario.expected_decision, response.decision))

    _print_header("SUMMARY")
    all_matched = True
    for label, expected, actual in results:
        ok = expected == actual
        all_matched = all_matched and ok
        print(f"{'OK  ' if ok else 'FAIL'}  {label}: expected {expected}, got {actual}")
    print()
    print(f"Audit log written to: {config.AUDIT_LOG_PATH}")

    if not all_matched:
        print(
            "\nNote: one or more scenarios did not match the expected decision.\n"
            "tool_name/arguments above are planned by a live LLM call\n"
            "(core.reasoning_layer.ReasoningLayer), not hardcoded, so wording\n"
            "the model settles on can vary between runs — inspect the audit\n"
            "log or re-run if a mismatch is unexpected."
        )


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        if "ANTHROPIC_API_KEY" in str(e) or "GROQ_API_KEY" in str(e):
            print(
                "Error: set ANTHROPIC_API_KEY or GROQ_API_KEY in .env or the "
                "environment (see utils.config.load_config's 'model.provider').",
                file=sys.stderr,
            )
            sys.exit(1)
        raise
    except APIStatusError as e:
        if _is_insufficient_credits_error(e):
            print(
                "\nAnthropic API: your account has no usable credits (balance too low).\n"
                "This is not an RMIC-Guard code error — the API refused the request.\n"
                "Fix: https://console.anthropic.com/ -> Plans & Billing -> add credits or upgrade.\n",
                file=sys.stderr,
            )
        else:
            print(f"\nAnthropic API error (HTTP {e.status_code}): {e.message}", file=sys.stderr)
        sys.exit(1)
    except AuthenticationError as e:
        print(f"\nAnthropic authentication failed: {e.message}", file=sys.stderr)
        print("Check ANTHROPIC_API_KEY in .env or the environment.", file=sys.stderr)
        sys.exit(1)
    except APIConnectionError as e:
        print(f"\nCould not reach Anthropic API (network): {e}", file=sys.stderr)
        sys.exit(1)