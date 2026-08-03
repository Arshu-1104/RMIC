"""
IBM watsonx Orchestrate custom tool registration for RMIC-Guard.

Wraps ibm_pilot.rmic_guard_tool.RMICGuardTool as a watsonx Orchestrate
Python tool, using the real ADK decorator surface:

    from ibm_watsonx_orchestrate.agent_builder.tools import tool

(verified against ibm-watsonx-orchestrate==2.13.0's actual
agent_builder/tools/python_tool.py — this is not a guessed API).

Import into a live Orchestrate environment with:
    orchestrate tools import -k python -f ibm_pilot/agent_example.py \
        -r ibm_pilot/requirements.txt

Then reference the tool by its registered name (config.IBM_TOOL_NAME) in an
agent's YAML `tools:` list. An example agent spec is included at the bottom
of this docstring — see the TODO next to it.

TODO markers throughout this file flag every place a watsonx Orchestrate ADK
behavioural assumption could not be verified against a *live* Orchestrate
instance in this environment (no Orchestrate subscription/API key was
available here — only the ADK's public Python package and documentation).
Re-check each TODO against your installed ADK version before deploying:
    pip show ibm-watsonx-orchestrate

--------------------------------------------------------------------------
Example agent YAML (TODO: verify field names against your ADK version —
this follows the `spec_version: v1` / `kind: native` shape documented at
https://developer.watson-orchestrate.ibm.com, not a live-tested deployment):

    spec_version: v1
    kind: native
    style: react
    name: rmic_guard_pilot_agent
    llm: watsonx/meta-llama/llama-3-1-70b-instruct
    instructions: |-
      You are a financial transfer agent. Before taking any action on the
      user's behalf, you MUST call the rmic_guard_tool tool with the
      user's message, the business tool you intend to call, and its
      arguments. Only proceed with the action if the tool returns
      decision: ALLOW. If it returns decision: BLOCK, explain to the user
      that the request cannot be completed and why (see the "reason" field).
    tools:
      - rmic_guard_tool
--------------------------------------------------------------------------
"""
from __future__ import annotations

from typing import Any

try:
    from ibm_watsonx_orchestrate.agent_builder.tools import ToolPermission, tool

    _WXO_ADK_AVAILABLE = True
except ImportError:
    # ibm-watsonx-orchestrate isn't installed in this environment. Fall back
    # to a no-op decorator so this module still imports and the underlying
    # function is still directly callable/testable without the ADK present.
    # Real registration with Orchestrate requires the real package:
    #   pip install ibm-watsonx-orchestrate
    _WXO_ADK_AVAILABLE = False

    def tool(*_args: Any, **_kwargs: Any):  # type: ignore[no-redef]
        def _decorator(fn):
            return fn

        return _decorator

    class ToolPermission:  # type: ignore[no-redef]
        READ_ONLY = "read_only"


from ibm_pilot import config
from ibm_pilot.rmic_guard_tool import IBMAgentRequest, RMICGuardTool

__all__ = ["check_and_execute_rmic_action"]


@tool(
    name=config.IBM_TOOL_NAME,
    display_name=config.IBM_TOOL_DISPLAY_NAME,
    description=config.IBM_TOOL_DESCRIPTION,
    # READ_ONLY here reflects that this tool only *checks* a proposed action;
    # the underlying business tool (transfer_funds etc.) is a separate stub
    # invoked internally on ALLOW. TODO: confirm with your Orchestrate admin
    # whether the pilot's actual business tools should instead be registered
    # as their own Orchestrate tools with non-read-only permission, rather
    # than being executed from inside this tool.
    permission=ToolPermission.READ_ONLY,
)
def check_and_execute_rmic_action(
    user_message: str,
    tool_name: str,
    amount: float | None = None,
    recipient_account: str | None = None,
) -> dict:
    """Checks a planned financial action against the RMIC-Guard identity
    contract, then executes it if — and only if — the contract allows it.

    This is the single entry point an IBM watsonx Orchestrate agent calls
    before performing any action on the financial_agent's behalf. It does
    not decide policy itself; it delegates entirely to the existing
    core.enforcement_engine.EnforcementEngine via RMICGuardTool.

    Args:
        user_message (str): The end user's original request, verbatim. Used
            for semantic drift scoring against the contract's anchors — do
            not summarise or rephrase it before passing it in.
        tool_name (str): The business tool the Orchestrate agent wants to
            call. Must be one of the financial_agent contract's
            allowed_actions to pass (e.g. "transfer_funds", "check_balance",
            "get_transaction_history", "send_transfer_confirmation").
        amount (float): Transfer amount, if tool_name is "transfer_funds".
            Checked against the contract's parameter_constraints (max 50000).
        recipient_account (str): Recipient account identifier, if tool_name
            is "transfer_funds".

    Returns:
        dict: IBMToolResponse.to_dict() — contains "decision" ("ALLOW" or
            "BLOCK"), "reason", "ids_score", "hard_rule_violation",
            "tool_result", and "contract_hash".
    """
    arguments: dict[str, Any] = {}
    if amount is not None:
        arguments["amount"] = amount
    if recipient_account is not None:
        arguments["recipient_account"] = recipient_account

    # TODO(production): watsonx Orchestrate Python tools run in isolated,
    # short-lived containers per invocation (see "Runtime and migration
    # strategy" / "Read only filesystem" in the ADK docs). A fresh
    # RMICGuardTool is therefore constructed on every call here, which means
    # its in-process trajectory state (_recent_ids / _tool_call_history,
    # used for IDS drift-velocity across a session) will NOT persist across
    # separate tool invocations in a hosted Orchestrate environment — each
    # call effectively starts a new session. For real multi-turn
    # drift-velocity tracking, that state needs to be threaded through the
    # ADK's AgentRun context object (see "Using Context Variables" in the
    # ADK docs) or persisted to an external store, not kept as a Python
    # instance attribute. This pilot intentionally ships with that
    # limitation; see README.md "Limitations".
    #
    # TODO(production): the "Read only filesystem" restriction documented
    # for hosted Python tools also applies to core.audit_ledger.AuditLedger,
    # which appends to a local JSONL file (config.AUDIT_LOG_PATH). That
    # local-disk write will not work in a hosted (non-Developer-Edition)
    # Orchestrate deployment. Reusing the existing AuditLedger class against
    # a writable/remote path (e.g. a mounted volume or an object-store-backed
    # file-like object) is required before this goes beyond a local pilot.
    guard_tool = RMICGuardTool()

    request = IBMAgentRequest(
        user_message=user_message,
        tool_name=tool_name,
        arguments=arguments,
    )

    response = guard_tool.handle_request(request, execute_tool=True)
    return response.to_dict()


if __name__ == "__main__":
    # Local self-test, runnable with or without the ADK installed:
    #   python -m ibm_pilot.agent_example
    # When the real ADK is installed, the decorated object is a PythonTool
    # instance whose original function is reachable via `.fn`; the fallback
    # no-op decorator above just returns the plain function.
    raw_fn = getattr(check_and_execute_rmic_action, "fn", check_and_execute_rmic_action)

    print(f"ADK installed: {_WXO_ADK_AVAILABLE}")
    result = raw_fn(
        user_message="Transfer 500 to account ending in 4321 for rent.",
        tool_name="transfer_funds",
        amount=500.0,
        recipient_account="4321",
    )
    print(result)