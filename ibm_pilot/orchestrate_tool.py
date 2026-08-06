"""
Python tool entry point for IBM watsonx Orchestrate.

This file exists purely to satisfy the ADK's import contract (a single
@tool-decorated function with typed params and a Google-style docstring).
It does not reimplement anything — it constructs the existing
ibm_pilot.rmic_guard_tool.RMICGuardTool exactly once at module load time
and calls its existing handle_request() method on every invocation.

Import into a live environment with:
    orchestrate tools import --kind python --file ibm_pilot/orchestrate_tool.py
"""
from __future__ import annotations

from ibm_watsonx_orchestrate.agent_builder.tools import tool

from ibm_pilot.rmic_guard_tool import IBMAgentRequest, RMICGuardTool

# Built once per container instance, reused across calls — mirrors how
# demo.py and agent_example.py construct a single RMICGuardTool for a run.
_guard = RMICGuardTool()


@tool()
def rmic_guard_check(
    user_message: str,
    tool_name: str,
    arguments: dict,
) -> dict:
    """Checks a planned agent tool call against the sealed RMIC identity
    contract before it is allowed to execute.

    Call this BEFORE running any business tool (transfer_funds,
    check_balance, get_transaction_history, send_transfer_confirmation).
    It returns ALLOW or BLOCK based on hard-rule checks and semantic
    identity-drift scoring against the agent's sealed role contract.

    Args:
        user_message: The original end-user request text, verbatim. Used
            for identity-drift scoring, not just the tool_name/arguments.
        tool_name: The business tool the agent wants to call (e.g.
            "transfer_funds", "check_balance").
        arguments: The arguments the agent wants to pass to that tool,
            e.g. {"amount": 500, "account_number": "4321"}.

    Returns:
        dict: Structured decision with keys "decision" ("ALLOW" or
            "BLOCK"), "raw_decision", "ids_score", "reason",
            "hard_rule_violation", "tool_result", and "contract_hash".
    """
    request = IBMAgentRequest(
        user_message=user_message,
        tool_name=tool_name,
        arguments=arguments or {},
    )
    response = _guard.handle_request(request)
    return response.to_dict()