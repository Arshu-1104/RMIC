"""
Standalone RMIC-Guard policy check for IBM watsonx Orchestrate.

This is the Healthcare Research Agent pilot implementation.
It mirrors the sealed healthcare_research_agent contract without
depending on the full RMIC-Guard core package.

The real contract is:
contracts/healthcare_research_agent.json
"""

from __future__ import annotations

import json

from ibm_watsonx_orchestrate.agent_builder.tools import tool


# ============================================================
# Healthcare Research Agent contract
# ============================================================

CONTRACT_AGENT_ID = "healthcare_research_agent"

ALLOWED_ACTIONS = {
    "search_pubmed",
    "search_arxiv",
    "retrieve_abstract",
    "cite_paper",
    "summarise_research",
    "generate_bibliography",
}

FORBIDDEN_ACTIONS = {
    "access_patient_records",
    "give_medical_advice",
    "write_prescription",
    "access_clinical_database",
    "provide_diagnosis",
    "recommend_treatment",
    "access_health_insurance_data",
    "reveal_patient_data",
    "execute_code",
}

PAPERS_MIN = 1
PAPERS_MAX = 20


# ============================================================
# Pilot stand-in for semantic identity-drift detection
# ============================================================
#
# The production RMIC engine uses embedding-based IDS.
# This standalone Orchestrate sandbox version uses explicit
# phrases so that the policy behavior can be demonstrated
# without requiring the full embedding stack.
#

DRIFT_PHRASES = (
    "forget that you're",
    "forget that you are",
    "forget you're",
    "forget you are",
    "from now on act as",
    "act as a doctor",
    "act as my doctor",
    "act as a clinician",
    "act as a medical advisor",
    "act as a healthcare advisor",
    "i am actually the doctor",
    "i'm actually the doctor",
    "ignore your role",
    "ignore your identity",
    "change your role",
    "change your identity",
    "you are now a doctor",
    "you are now a clinician",
)


# ============================================================
# Direct prohibited-intent phrases
# ============================================================

PROHIBITED_INTENT_PHRASES = {
    "give_medical_advice": (
        "give me medical advice",
        "provide medical advice",
        "medical advice",
    ),
    "write_prescription": (
        "write a prescription",
        "give me a prescription",
        "prescribe medicine",
        "prescribe medication",
    ),
    "provide_diagnosis": (
        "diagnose me",
        "give me a diagnosis",
        "what is my diagnosis",
    ),
    "recommend_treatment": (
        "recommend a treatment",
        "recommend treatment",
        "tell me what treatment i need",
        "what treatment should i take",
    ),
    "access_patient_records": (
        "access patient records",
        "access a patient's records",
        "show patient records",
    ),
    "access_clinical_database": (
        "access the clinical database",
        "access clinical database",
    ),
    "access_health_insurance_data": (
        "access health insurance data",
        "show health insurance data",
    ),
    "reveal_patient_data": (
        "reveal patient data",
        "show patient data",
        "give me patient data",
    ),
    "execute_code": (
        "execute code",
        "run arbitrary code",
        "run this code",
    ),
}


@tool()
def rmic_healthcare_guard_check(
    user_message: str,
    tool_name: str,
    arguments_json: str = "{}",
) -> dict:
    """
    Check a planned Healthcare Research Agent action against
    the sealed RMIC identity contract.

    This tool MUST be called before responding to every user
    message.

    Args:
        user_message:
            Exact original user message.

        tool_name:
            One of:
              search_pubmed
              search_arxiv
              retrieve_abstract
              cite_paper
              summarise_research
              generate_bibliography
              or a forbidden action name.
            Use general_query for messages that do not request
            a specific action.

        arguments_json:
            JSON string containing extracted parameters.

    Returns:
        A dictionary containing:
          decision: ALLOW or BLOCK
          reason
          contract_agent_id
    """

    # --------------------------------------------------------
    # Parse arguments
    # --------------------------------------------------------

    try:
        arguments = json.loads(arguments_json) if arguments_json else {}
        if not isinstance(arguments, dict):
            arguments = {}
    except (json.JSONDecodeError, TypeError):
        arguments = {}

    lowered_msg = (user_message or "").lower()

    # --------------------------------------------------------
    # 1. Identity drift detection
    # --------------------------------------------------------

    for phrase in DRIFT_PHRASES:
        if phrase in lowered_msg:
            return {
                "decision": "BLOCK",
                "reason": f"identity_drift_phrase_detected:{phrase!r}",
                "contract_agent_id": CONTRACT_AGENT_ID,
            }

    # --------------------------------------------------------
    # 2. Direct prohibited intent detection
    # --------------------------------------------------------

    for forbidden_action, phrases in PROHIBITED_INTENT_PHRASES.items():
        for phrase in phrases:
            if phrase in lowered_msg:
                return {
                    "decision": "BLOCK",
                    "reason": f"forbidden_action:{forbidden_action}",
                    "contract_agent_id": CONTRACT_AGENT_ID,
                }

    # --------------------------------------------------------
    # 3. General query
    # --------------------------------------------------------

    if tool_name == "general_query":
        return {
            "decision": "ALLOW",
            "reason": "ALLOWED_legitimate_research_query_passed_all_checks",
            "contract_agent_id": CONTRACT_AGENT_ID,
        }

    # --------------------------------------------------------
    # 4. Forbidden action check
    # --------------------------------------------------------

    if tool_name in FORBIDDEN_ACTIONS:
        return {
            "decision": "BLOCK",
            "reason": f"forbidden_action:{tool_name}",
            "contract_agent_id": CONTRACT_AGENT_ID,
        }

    # --------------------------------------------------------
    # 5. Allowed action whitelist
    # --------------------------------------------------------

    if tool_name not in ALLOWED_ACTIONS:
        return {
            "decision": "BLOCK",
            "reason": f"tool_not_in_allowed_actions:{tool_name}",
            "contract_agent_id": CONTRACT_AGENT_ID,
        }

    # --------------------------------------------------------
    # 6. papers_per_query constraint
    # --------------------------------------------------------

    if "papers_per_query" in arguments:
        try:
            papers = int(arguments["papers_per_query"])
        except (TypeError, ValueError):
            return {
                "decision": "BLOCK",
                "reason": "parameter_constraint:papers_per_query:not_integer",
                "contract_agent_id": CONTRACT_AGENT_ID,
            }

        if papers < PAPERS_MIN:
            return {
                "decision": "BLOCK",
                "reason": "parameter_constraint:papers_per_query:below_min",
                "contract_agent_id": CONTRACT_AGENT_ID,
            }

        if papers > PAPERS_MAX:
            return {
                "decision": "BLOCK",
                "reason": "parameter_constraint:papers_per_query:above_max",
                "contract_agent_id": CONTRACT_AGENT_ID,
            }

    # --------------------------------------------------------
    # 7. Explicit escalation flags
    # --------------------------------------------------------

    for flag in (
        "admin",
        "admin_approval",
        "override",
        "override_policy",
        "bypass_guard",
        "ignore_contract",
    ):
        if arguments.get(flag):
            return {
                "decision": "BLOCK",
                "reason": f"forbidden_argument_flag:{flag}",
                "contract_agent_id": CONTRACT_AGENT_ID,
            }

    # --------------------------------------------------------
    # 8. Passed all checks
    # --------------------------------------------------------

    return {
        "decision": "ALLOW",
        "reason": "passed_all_checks",
        "contract_agent_id": CONTRACT_AGENT_ID,
    }
