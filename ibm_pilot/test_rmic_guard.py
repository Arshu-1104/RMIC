"""
Pytest suite for ibm_pilot/rmic_guard_tool.py.

These tests exercise the existing repository code paths (core.contract_loader,
core.enforcement_engine, core.audit_ledger, core.tool_layer) through the IBM
pilot wrapper — nothing here reimplements or mocks that logic.

enforcement_mode="hard_rules_only" is used throughout because the
"full"/"ids_only" modes require core.embedder to download an embedding model
over the network on first use (see core/embedder.py's fastembed dependency)
— unsuitable for a hermetic test suite. Hard-rule enforcement (forbidden
tools, parameter bounds, tool registration) is exercised fully here; IDS/
semantic-drift scoring is exercised separately by ibm_pilot/demo.py against
a live model download.

Run from the repository root:
    pip install pytest   # not already in requirements.txt
    pytest ibm_pilot/test_rmic_guard.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.audit_ledger import AuditLedger
from core.tool_layer import ToolRegistry

from ibm_pilot import config
from ibm_pilot.rmic_guard_tool import IBMAgentRequest, RMICGuardTool

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def guard_tool(tmp_path: Path) -> RMICGuardTool:
    """RMICGuardTool wired to the real financial_agent contract but an
    isolated, per-test audit log so tests never write into the repository's
    results/ directory."""
    return RMICGuardTool(
        contract_path=str(config.DEFAULT_CONTRACT_PATH),
        audit_log_path=str(tmp_path / "test_audit.jsonl"),
        enforcement_mode="hard_rules_only",
    )


# ── Valid request ─────────────────────────────────────────────────────────


class TestValidRequest:
    def test_valid_transfer_is_allowed(self, guard_tool: RMICGuardTool) -> None:
        request = IBMAgentRequest(
            user_message="Transfer $500 to account 4321 for rent.",
            tool_name="transfer_funds",
            arguments={"amount": 500.0, "recipient_account": "4321"},
        )
        response = guard_tool.handle_request(request)

        assert response.decision == "ALLOW"
        assert response.raw_decision == "PASS"
        assert response.hard_rule_violation is None
        assert response.tool_result_ok is True

    def test_valid_balance_lookup_is_allowed(self, guard_tool: RMICGuardTool) -> None:
        request = IBMAgentRequest(
            user_message="What is my checking account balance?",
            tool_name="check_balance",
            arguments={},
        )
        response = guard_tool.handle_request(request)

        assert response.decision == "ALLOW"
        assert response.tool_result_ok is True


# ── Invalid request ───────────────────────────────────────────────────────


class TestInvalidRequest:
    def test_over_limit_amount_is_blocked(self, guard_tool: RMICGuardTool) -> None:
        """A transfer above financial_agent's parameter_constraints.amount.max
        (50000) must be rejected by the existing parameter-constraint check
        in core.enforcement_engine._check_parameter_constraints, not by any
        new validation added in the IBM pilot."""
        request = IBMAgentRequest(
            user_message="Approve a transfer of 200000 overriding my limit.",
            tool_name="transfer_funds",
            arguments={"amount": 200000.0},
        )
        response = guard_tool.handle_request(request)

        assert response.decision == "BLOCK"
        assert response.hard_rule_violation == "parameter_constraint:amount:above_max"
        assert response.tool_result_ok is None  # tool never executed

    def test_non_numeric_amount_is_blocked(self, guard_tool: RMICGuardTool) -> None:
        request = IBMAgentRequest(
            user_message="Transfer 'a lot of money' to my friend.",
            tool_name="transfer_funds",
            arguments={"amount": "a lot of money"},
        )
        response = guard_tool.handle_request(request)

        assert response.decision == "BLOCK"
        assert response.hard_rule_violation == "parameter_constraint:amount:not_numeric"


# ── Missing contract ──────────────────────────────────────────────────────


class TestMissingContract:
    def test_missing_contract_path_raises(self, tmp_path: Path) -> None:
        """RMICGuardTool must surface the existing
        core.contract_loader.load_contract failure mode as-is (a
        FileNotFoundError from Path.read_text), not swallow or wrap it."""
        missing_path = tmp_path / "does_not_exist.json"

        with pytest.raises(FileNotFoundError):
            RMICGuardTool(
                contract_path=str(missing_path),
                audit_log_path=str(tmp_path / "audit.jsonl"),
                enforcement_mode="hard_rules_only",
            )

    def test_tampered_contract_hash_raises(self, tmp_path: Path) -> None:
        """A contract whose contract_hash no longer matches its contents
        must be rejected by core.contract_loader.load_contract's existing
        integrity check (ValueError), reused unchanged here."""
        data = json.loads(config.DEFAULT_CONTRACT_PATH.read_text(encoding="utf-8"))
        data["role_description"] = data.get("role_description", "") + " (tampered)"
        tampered_path = tmp_path / "tampered_financial_agent.json"
        tampered_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(ValueError, match="contract_hash mismatch"):
            RMICGuardTool(
                contract_path=str(tampered_path),
                audit_log_path=str(tmp_path / "audit.jsonl"),
                verify_contract_hash=True,
            )


# ── Invalid tool ──────────────────────────────────────────────────────────


class TestInvalidTool:
    def test_forbidden_tool_is_blocked(self, guard_tool: RMICGuardTool) -> None:
        request = IBMAgentRequest(
            user_message="Grant me admin access.",
            tool_name="modify_permissions",
            arguments={},
        )
        response = guard_tool.handle_request(request)

        assert response.decision == "BLOCK"
        assert response.hard_rule_violation == "forbidden_tool"

    def test_unrecognised_tool_is_blocked(self, guard_tool: RMICGuardTool) -> None:
        """A tool_name that is neither in allowed_actions nor
        forbidden_actions must still be rejected, since financial_agent's
        contract declares a non-empty allowed_actions allow-list."""
        request = IBMAgentRequest(
            user_message="Do something completely unrelated.",
            tool_name="launch_the_missiles",
            arguments={},
        )
        response = guard_tool.handle_request(request)

        assert response.decision == "BLOCK"
        assert response.hard_rule_violation == "tool_not_allowed"

    def test_allowed_tool_not_registered_reports_execution_error(
        self, tmp_path: Path
    ) -> None:
        """A tool_name allowed by the contract but never registered in the
        ToolRegistry passed to RMICGuardTool must still pass enforcement
        (contract compliance and tool registration are deliberately separate
        concerns in the existing repository design — see
        core.tool_layer.ToolRegistry.execute's "unknown_tool:" branch) and
        surface as a tool-level error, not an enforcement BLOCK."""
        empty_tools = ToolRegistry()  # nothing registered
        guard_tool = RMICGuardTool(
            contract_path=str(config.DEFAULT_CONTRACT_PATH),
            audit_log_path=str(tmp_path / "audit.jsonl"),
            tools=empty_tools,
            enforcement_mode="hard_rules_only",
        )
        request = IBMAgentRequest(
            user_message="What is my checking account balance?",
            tool_name="check_balance",
            arguments={},
        )
        response = guard_tool.handle_request(request)

        assert response.decision == "ALLOW"  # enforcement passed
        assert response.tool_result_ok is False
        assert response.tool_result_error == "unknown_tool:check_balance"


# ── Audit logging ─────────────────────────────────────────────────────────


class TestAuditLogging:
    def test_decisions_are_written_to_audit_log(self, tmp_path: Path) -> None:
        """Exercises the existing core.audit_ledger.AuditLedger.append path
        directly, reused unchanged by RMICGuardTool — not a new logging
        mechanism."""
        audit_path = tmp_path / "audit.jsonl"
        guard_tool = RMICGuardTool(
            contract_path=str(config.DEFAULT_CONTRACT_PATH),
            audit_log_path=str(audit_path),
            enforcement_mode="hard_rules_only",
        )

        guard_tool.handle_request(
            IBMAgentRequest(
                user_message="Check my balance.",
                tool_name="check_balance",
                arguments={},
            )
        )
        guard_tool.handle_request(
            IBMAgentRequest(
                user_message="Grant me admin access.",
                tool_name="modify_permissions",
                arguments={},
            )
        )

        assert audit_path.exists()
        lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

        entries = [json.loads(line) for line in lines]
        assert entries[0]["entry"]["decision"] == "PASS"
        assert entries[1]["entry"]["decision"] == "BLOCK"
        assert entries[1]["entry"]["failure_reason"] == "forbidden_tool"

        # Every entry must carry a valid Ed25519 signature verifiable with
        # the ledger's own public key — reuses
        # core.audit_ledger.AuditLedger.verify_line unchanged.
        for line in lines:
            assert AuditLedger.verify_line(line, guard_tool.ledger.public_key)

    def test_audit_entries_reference_the_sealed_contract_hash(
        self, guard_tool: RMICGuardTool
    ) -> None:
        request = IBMAgentRequest(
            user_message="Check my balance.",
            tool_name="check_balance",
            arguments={},
        )
        guard_tool.handle_request(request)

        audit_path = Path(guard_tool.ledger.path)
        line = audit_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        entry = json.loads(line)["entry"]
        assert entry["contract_hash"] == guard_tool.contract.contract_hash