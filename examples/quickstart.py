"""RMIC-Guard quickstart -- runs fully offline (no API key, no network, no model download).

    pip install rmic-guard
    python examples/quickstart.py

semantic=False enforces the contract's hard rules (forbidden tools, parameter
bounds, data scope) without an embedding model. Drop it to add semantic
identity-drift detection (downloads BAAI/bge-small-en-v1.5 once), and see
guard.run(...) in the README for letting an LLM plan the tool call.
"""

from rmic_guard import Guard

guard = Guard({"agent_id": "bot", "role_name": "Bot", "sector": "demo",
               "semantic_anchors": ["I check account balances."],
               "allowed_actions": ["check_balance"], "forbidden_actions": ["admin_login"]},
              semantic=False)
guard.register("check_balance", lambda: {"balance": 100})
guard.register("admin_login", lambda: "root shell")  # registered, but the contract forbids it

print(guard.check("check_balance"))  # allowed=True,  decision=PASS,  output={'balance': 100}
print(guard.check("admin_login"))    # allowed=False, decision=BLOCK, reason=forbidden_tool

assert guard.check("check_balance").allowed and not guard.check("admin_login").executed
