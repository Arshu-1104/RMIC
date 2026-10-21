"""Run one request through the IBM pilot guard (support_agent).

Run from the repository root:
    python ibm_pilot/run_single.py

The contract is loaded with load_contract(): a sealed file is hash-verified,
and an unsealed one is sealed in memory only. This script never writes the
contract file, so the frozen research contracts stay byte-identical.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ibm_pilot import config  # noqa: E402  (sets RMIC_CONFIG before the SDK reads it)
from ibm_pilot.rmic_guard_tool import IBMAgentRequest, RMICGuardTool  # noqa: E402
from rmic_guard._core.contract_loader import load_contract  # noqa: E402


def main():
    path = config.CONTRACT_PATHS["support_agent"]

    print("=== RMIC-GUARD SINGLE RUN ===")

    print("\n[1] Loading contract (verified if sealed, else sealed in memory; never written)...")
    contract = load_contract(path)
    print("OK:", contract.contract_hash[:12] + "...")

    print("\n[2] Running RMIC Guard...")
    guard = RMICGuardTool(contract_path=str(path))

    request = IBMAgentRequest(
        user_message="Please search the knowledge base for the procedure to update billing information",
        tool_name="search_kb",
    )

    result = guard.handle_request(request, execute_tool=False)

    print("\n=== RESULT ===")
    print("Decision :", result.decision)
    print("IDS Score:", f"{result.ids_score:.4f}")
    print("Reason   :", result.reason)
    print("Hash     :", result.contract_hash[:12] + "...")
    print("Audit    :", config.AUDIT_LOG_PATH)


if __name__ == "__main__":
    main()
