"""SDK-specific exceptions for RMIC-Guard.

All errors raised by the public API inherit from RMICGuardError so callers
can catch a single base class, while still being able to catch the more
specific subclasses when they need to branch on failure type.
"""

from __future__ import annotations

__all__ = [
    "RMICGuardError",
    "InvalidContractError",
    "ContractIntegrityError",
    "ContractNotSealedError",
    "ToolNotRegisteredError",
    "ToolExecutionNotApprovedError",
    "EnforcementConfigError",
]


class RMICGuardError(Exception):
    """Base class for every error raised by rmic-guard."""


class InvalidContractError(RMICGuardError):
    """Raised when a contract dict/JSON file fails schema validation.

    Carries a list of individual field-level problems so callers (and the
    CLI) can print each one instead of a single opaque message.
    """

    def __init__(self, problems: list[str], *, source: str | None = None) -> None:
        self.problems = list(problems)
        self.source = source
        header = "Invalid RMIC contract"
        if source:
            header += f" ({source})"
        body = "\n".join(f"  - {p}" for p in self.problems)
        message = (
            f"{header}:\n{body}\n\n"
            "See the RMIC contract schema: schema/contract.schema.json in a repo clone, "
            "or rmic_guard/schema/contract.schema.json inside an installed rmic-guard package "
            "(https://github.com/Arshu-1104/RMIC/blob/main/schema/contract.schema.json)."
        )
        super().__init__(message)


class ContractIntegrityError(RMICGuardError):
    """Raised when a sealed contract's stored hash does not match its content."""


class ContractNotSealedError(RMICGuardError):
    """Raised when an operation requires anchor_embedding/contract_hash but the
    contract was never sealed (e.g. computing IDS on an unsealed contract)."""


class ToolNotRegisteredError(RMICGuardError):
    """Raised when a tool call targets a name that was never registered."""


class ToolExecutionNotApprovedError(RMICGuardError):
    """Raised when tool execution is attempted without a valid enforcement
    engine approval token (defence against bypassing the enforcement engine)."""


class EnforcementConfigError(RMICGuardError):
    """Raised for invalid EnforcementEngine configuration (e.g. bad thresholds)."""
