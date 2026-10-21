"""RMIC-Guard quickstart -- runs fully offline (no API key, no network, no model download).

    pip install rmic-guard
    python examples/quickstart.py

Uses the bundled, pre-sealed financial_agent contract. semantic=False (the
default, spelled out below) enforces the contract's hard rules (forbidden
tools, parameter bounds, data scope) without an embedding model.
semantic=True adds experimental identity-drift detection (downloads
BAAI/bge-small-en-v1.5 once); see guard.run(...) in the README for letting an
LLM plan the tool call.
"""

from rmic_guard import Guard, load_example_contract

guard = Guard(load_example_contract("financial_agent"), semantic=False)
guard.register("check_balance", lambda: {"balance": 100})
guard.register("transfer_funds", lambda amount, to_account: {"sent": amount, "to": to_account})
guard.register("admin_login", lambda: "root shell")  # registered, but the contract forbids it

print(guard.check("check_balance"))                                   # PASS, output={'balance': 100}
print(guard.check("admin_login"))                                     # BLOCK, reason=forbidden_tool
print(guard.check("transfer_funds", amount=90000, to_account="4321"))  # BLOCK, above the 50,000 max

assert guard.check("check_balance").allowed and not guard.check("admin_login").executed
assert guard.check("transfer_funds", amount=90000, to_account="4321").reason == "parameter_constraint:amount:above_max"
