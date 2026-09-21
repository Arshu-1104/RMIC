from core.contract_loader import seal_contract_file, load_contract
from ibm_pilot.rmic_guard_tool import RMICGuardTool, IBMAgentRequest
from ibm_pilot import config

def main():
    path = config.CONTRACT_PATHS["support_agent"]

    print("=== RMIC-GUARD SINGLE RUN ===")

    print("\n[1] Sealing contract...")
    contract = seal_contract_file(path, write_back=True)
    print("OK:", contract.contract_hash[:12] + "...")

    print("\n[2] Verifying contract...")
    load_contract(path, verify_hash=True)
    print("OK: hash verified")

    print("\n[3] Running RMIC Guard...")
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