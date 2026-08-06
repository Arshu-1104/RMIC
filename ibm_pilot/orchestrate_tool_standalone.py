"""
Self-contained RMIC-Guard policy check for IBM watsonx Orchestrate.

Unlike ibm_pilot/orchestrate_tool.py (which imports the full RMIC-Guard
enforcement engine from core/), this file has ZERO local-module
dependencies. Orchestrate's Python-tool sandbox only receives the single
file passed to `orchestrate tools import`, plus pip packages listed in a
requirements.txt -- it does NOT bundle sibling files or packages like
core/ or ibm_pilot/. This file works around that by inlining the sealed
financial_agent contract's rules directly, so it runs standalone inside
the sandbox with no imports beyond the ADK itself.

This is a PILOT-SCOPE reimplementation for the Orchestrate demo only.
It intentionally does NOT reproduce the semantic identity-drift (IDS)
scoring from core/enforcement_engine.py, which depends on an embedding
model not available in this sandbox. It DOES enforce, from the real
sealed contract (contracts/financial_agent.json):
  - the allowed_actions whitelist
  - the forbidden_actions blacklist
  - the amount parameter_constraint (min 0.01, max 50000.0)
  - a keyword-based stand-in for identity-drift phrases (e.g. "forget
    that you're", "act as", "admin", "override"), since the real
    embedding-based IDS check isn't portable into this sandbox.

Import into a live environment with:
    orchestrate tools import --kind python --file ibm_pilot/orchestrate_tool_standalone.py
"""
from __future__ import annotations

import json

from ibm_watsonx_orchestrate.agent_builder.tools import tool

# ── Inlined from contracts/financial_agent.json (sealed contract_hash
#    da606eba074217d02ae36de19e051fe594bfb2ce3de48a7c633ead91bbf93b8d)
#    Keep this in sync manually if the contract is re-sealed. ──────────────
ALLOWED_ACTIONS = {
    "transfer_funds",
    "check_balance",
    "get_transaction_history",
    "send_transfer_confirmation",
}
FORBIDDEN_ACTIONS = {
    "give_investment_advice",
    "share_customer_pii",
    "perform_account_transactions",
    "execute_code",
    "create_account",
    "delete_account",
    "modify_permissions",
    "admin_login",
    "bulk_transfer",
    "override_limit",
}
AMOUNT_MIN = 0.01
AMOUNT_MAX = 50000.0

# Keyword-based stand-in for the real semantic identity-drift scoring in
# core/enforcement_engine.py (which needs an embedding model this sandbox
# doesn't have). Matches phrasing patterns used in the demo's identity
# drift and permission escalation scenarios.
DRIFT_PHRASES = (
    "forget that you're",
    "forget you are",
    "act as a general",
    "act as a financial advisor",
    "from now on act as",
    "i'm actually the",
    "i am actually the",
    "bank administrator",
    "grant me admin",
    "modify my permissions",
    "override the normal",
    "override limit",
)


@tool()
def rmic_guard_check(
    user_message: str,
    tool_name: str,
    arguments_json: str = "{}",
) -> dict:
    """Checks a planned financial action against the sealed RMIC identity
    contract before it is allowed to execute. You MUST call this tool
    before responding to ANY user message, even ones that do not look
    like a transfer or balance request (e.g. investment-advice requests,
    or messages that ask you to change your role or behavior) -- pass
    tool_name="general_query" for those. Do not answer directly without
    calling this tool first.

    Args:
        user_message: The user's exact original message text, copied
            verbatim, with nothing paraphrased or summarized.
        tool_name: One of exactly: "transfer_funds", "check_balance",
            "get_transaction_history", "send_transfer_confirmation", or
            "general_query" if the message does not request one of those
            four actions.
        arguments_json: A JSON-encoded string (not an object) of any
            parameters extracted from the message, for example
            '{"amount": 500, "account_number": "4321"}'. Use "{}" if
            there are none.

    Returns:
        dict: Decision with keys "decision" ("ALLOW" or "BLOCK"),
            "reason", and "contract_agent_id".
    """
    try:
        arguments = json.loads(arguments_json) if arguments_json else {}
        if not isinstance(arguments, dict):
            arguments = {}
    except (json.JSONDecodeError, TypeError):
        arguments = {}
    lowered_msg = (user_message or "").lower()

    # 1. Identity-drift / permission-escalation phrasing in the message
    #    itself -- checked first, since this can apply even to an
    #    otherwise "allowed" tool_name (e.g. check_balance used as cover
    #    for a role-drift attempt).
    for phrase in DRIFT_PHRASES:
        if phrase in lowered_msg:
            return {
                "decision": "BLOCK",
                "reason": f"identity_drift_phrase_detected:{phrase!r}",
                "contract_agent_id": "financial_agent",
            }

    # 2. general_query is not a business tool call -- it's already been
    #    screened by the drift-phrase check above, so nothing further to
    #    enforce (no parameter constraints apply to a non-action message).
    if tool_name == "general_query":
        return {
            "decision": "ALLOW",
            "reason": "non_action_query_passed_drift_check",
            "contract_agent_id": "financial_agent",
        }

    # 3. Forbidden action check
    if tool_name in FORBIDDEN_ACTIONS:
        return {
            "decision": "BLOCK",
            "reason": f"forbidden_action:{tool_name}",
            "contract_agent_id": "financial_agent",
        }

    # 4. Allowed-tools whitelist check
    if tool_name not in ALLOWED_ACTIONS:
        return {
            "decision": "BLOCK",
            "reason": f"tool_not_in_allowed_actions:{tool_name}",
            "contract_agent_id": "financial_agent",
        }

    # 4. Parameter constraint: amount must be within [AMOUNT_MIN, AMOUNT_MAX]
    if "amount" in arguments:
        try:
            amount = float(arguments["amount"])
        except (TypeError, ValueError):
            return {
                "decision": "BLOCK",
                "reason": "parameter_constraint:amount:not_numeric",
                "contract_agent_id": "financial_agent",
            }
        if amount < AMOUNT_MIN or amount > AMOUNT_MAX:
            return {
                "decision": "BLOCK",
                "reason": "parameter_constraint:amount:above_max"
                if amount > AMOUNT_MAX
                else "parameter_constraint:amount:below_min",
                "contract_agent_id": "financial_agent",
            }

    # 5. Explicit override/admin flags in arguments (covers the
    #    permission-escalation scenario even if it slipped past the
    #    message-level phrase check)
    for flag in ("override_limit", "admin_approval", "admin_approved"):
        if arguments.get(flag):
            return {
                "decision": "BLOCK",
                "reason": f"forbidden_argument_flag:{flag}",
                "contract_agent_id": "financial_agent",
            }

    return {
        "decision": "ALLOW",
        "reason": "passed_all_checks",
        "contract_agent_id": "financial_agent",
    }