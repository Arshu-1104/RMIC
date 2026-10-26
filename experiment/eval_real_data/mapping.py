"""Pre-registered mappings for the real-data evaluation (see PLAN.md).

Banking77 intents are mapped to the financial_agent_hardened tools from the intent NAME only:

  1. a name containing "balance"                         -> check_balance
  2. else a name containing "transfer", "top_up" or
     "topping_up" (transfer / top-up / payment sending)   -> transfer_funds
  3. everything else -> the contract's support/ticket tool; it has none, so check_balance

Transfers get an amount from a seeded log-normal (median 1,500, sigma 1.0, seed 42, capped at
49,999.99, below the contract max of 50,000; rounded to cents) and an 8-digit account number,
both drawn in dataset order for every Banking77 row (so the draws do not depend on the mapping).
"""

from __future__ import annotations

import math
import random
from typing import Iterable, Iterator

SEED = 42
MEDIAN_AMOUNT = 1500.0
SIGMA = 1.0
AMOUNT_CAP = 49_999.99  # below the contract's parameter_constraints.amount.max (50,000)
GANDALF_AMOUNT = 500
GANDALF_ACCOUNT = "12345678"

TRANSFER_KEYWORDS = ("transfer", "top_up", "topping_up")


def tool_for_intent(intent: str) -> str:
    name = intent.lower()
    if "balance" in name:
        return "check_balance"
    if any(k in name for k in TRANSFER_KEYWORDS):
        return "transfer_funds"
    return "check_balance"  # no support/ticket tool in financial_agent_hardened


def rule_for_intent(intent: str) -> str:
    """Which of the three rules above decided the tool (for the plan's table)."""
    name = intent.lower()
    if "balance" in name:
        return "balance"
    if any(k in name for k in TRANSFER_KEYWORDS):
        return "transfer/top-up"
    return "other"


def draws(n: int, seed: int = SEED) -> Iterator[tuple[float, str]]:
    """(amount, account) for each of n rows, in order."""
    rng = random.Random(seed)
    mu = math.log(MEDIAN_AMOUNT)
    for _ in range(n):
        amount = min(rng.lognormvariate(mu, SIGMA), AMOUNT_CAP)
        account = str(rng.randrange(10_000_000, 100_000_000))
        yield max(round(amount, 2), 0.01), account


def banking_calls(intents: Iterable[str], seed: int = SEED) -> list[tuple[str, dict]]:
    """(tool, arguments) for each Banking77 row, in dataset order."""
    intents = list(intents)
    out = []
    for intent, (amount, account) in zip(intents, draws(len(intents), seed)):
        tool = tool_for_intent(intent)
        out.append((tool, {"amount": amount, "to_account": account} if tool == "transfer_funds" else {}))
    return out


def gandalf_calls() -> list[tuple[str, dict]]:
    """The two allowed, in-limit actions every Gandalf prompt is sent with."""
    return [
        ("transfer_funds", {"amount": GANDALF_AMOUNT, "to_account": GANDALF_ACCOUNT}),
        ("check_balance", {}),
    ]
