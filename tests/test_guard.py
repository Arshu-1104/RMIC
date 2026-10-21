"""Tests for the high-level Guard API and the v0.3 defect fixes it relies on.

All offline: the fake embedding backend from tests/conftest.py is active for
semantic=True guards; semantic=False guards never touch an embedding model.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from rmic_guard import (
    AuditLedger,
    ContractIntegrityError,
    EnforcementEngine,
    Guard,
    GuardResult,
    PlannedToolCall,
    RMICContract,
    RMICGuardError,
    ToolRegistry,
)
from rmic_guard._core import embedder
from rmic_guard._core.enforcement_engine import EnforcementOutcome
from rmic_guard._utils import config as rmic_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def _contract_dict(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "agent_id": "bank-bot",
        "role_name": "Bank Bot",
        "sector": "finance",
        "semantic_anchors": ["I help customers check balances and transfer funds."],
        "allowed_actions": ["transfer_funds", "check_balance"],
        "forbidden_actions": ["admin_login"],
        "parameter_constraints": {"amount": {"min": 0, "max": 1000, "type": "float"}},
        "data_scope": {"prohibited": ["medical_records"]},
    }
    data.update(overrides)
    return data


def _write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data, indent=2))
    return path


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch: pytest.MonkeyPatch) -> None:
    # The research entry points set RMIC_CONFIG; tests must not inherit it.
    monkeypatch.delenv("RMIC_CONFIG", raising=False)
    monkeypatch.delenv("RMIC_AUDIT_KEY", raising=False)


# ── contract loading / sealing ──────────────────────────────────────────────


class TestContractLoading:
    def test_unsealed_path_is_sealed_in_memory_and_file_untouched(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "bot.json", _contract_dict())
        before = path.read_text()

        guard = Guard(path)

        assert guard.contract.contract_hash
        assert guard.contract.anchor_embedding  # semantic=True embeds anchors
        assert path.read_text() == before

    def test_unsealed_path_hard_rules_only_has_no_embedding(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "bot.json", _contract_dict())
        guard = Guard(path, semantic=False)
        assert guard.contract.contract_hash
        assert guard.contract.anchor_embedding == ()

    def test_save_sealed_writes_back(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "bot.json", _contract_dict())
        guard = Guard(path, save_sealed=True)

        on_disk = json.loads(path.read_text())
        assert on_disk["contract_hash"] == guard.contract.contract_hash
        # A second Guard now verifies (rather than re-seals) the same file.
        assert Guard(path).contract.contract_hash == guard.contract.contract_hash

    def test_tampered_sealed_contract_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bot.json"
        Guard(_write(path, _contract_dict()), save_sealed=True)
        data = json.loads(path.read_text())
        data["forbidden_actions"] = []  # tamper after sealing
        path.write_text(json.dumps(data))

        with pytest.raises(ContractIntegrityError):
            Guard(path)

    def test_accepts_dict_and_rmic_contract(self) -> None:
        contract = RMICContract.create(**_contract_dict(), require_embedding=False)
        assert Guard(contract, semantic=False).contract is contract
        assert Guard(_contract_dict(), semantic=False).contract.agent_id == "bank-bot"

    def test_semantic_guard_rejects_contract_without_embedding(self) -> None:
        contract = RMICContract.create(**_contract_dict(), require_embedding=False)
        with pytest.raises(RMICGuardError, match="semantic=False"):
            Guard(contract)

    def test_save_sealed_requires_a_path(self) -> None:
        with pytest.raises(ValueError):
            Guard(_contract_dict(), semantic=False, save_sealed=True)


# ── check() ─────────────────────────────────────────────────────────────────


class TestCheck:
    def _guard(self, **kwargs: Any) -> tuple[Guard, list[str]]:
        calls: list[str] = []
        guard = Guard(_contract_dict(), semantic=False, **kwargs)

        @guard.tool
        def transfer_funds(amount: float, to: str) -> dict[str, Any]:
            calls.append("transfer_funds")
            return {"sent": amount, "to": to}

        @guard.tool("admin_login")
        def _admin() -> str:
            calls.append("admin_login")
            return "root"

        return guard, calls

    def test_allowed_tool_passes_and_returns_output(self) -> None:
        guard, calls = self._guard()
        result = guard.check("transfer_funds", amount=500, to="4321", message="pay rent")

        assert isinstance(result, GuardResult)
        assert result.allowed and result.decision == "PASS" and result.reason is None
        assert result.output == {"sent": 500, "to": "4321"}
        assert result.executed and calls == ["transfer_funds"]
        assert result.contract_hash == guard.contract.contract_hash

    def test_forbidden_tool_blocks_and_is_never_called(self) -> None:
        guard, calls = self._guard()
        result = guard.check("admin_login")

        assert not result.allowed
        assert result.decision == "BLOCK"
        assert result.reason == "forbidden_tool"
        assert result.output is None and not result.executed
        assert calls == []

    def test_parameter_above_max_blocks(self) -> None:
        guard, calls = self._guard()
        result = guard.check("transfer_funds", amount=5000, to="4321")
        assert result.decision == "BLOCK"
        assert result.reason == "parameter_constraint:amount:above_max"
        assert calls == []

    def test_prohibited_data_category_blocks(self) -> None:
        guard, calls = self._guard()
        result = guard.check("transfer_funds", amount=10, to="4321", data=["medical_records"])
        assert result.decision == "BLOCK"
        assert result.reason == "data_scope:prohibited:medical_records"
        assert calls == []

    def test_reserved_names_can_be_passed_via_arguments(self) -> None:
        seen: dict[str, Any] = {}
        guard = Guard(_contract_dict(), semantic=False)
        guard.register("check_balance", lambda **kw: seen.update(kw) or "ok")
        result = guard.check("check_balance", arguments={"data": "x", "message": "y"}, account="1")
        assert result.allowed and seen == {"data": "x", "message": "y", "account": "1"}

    def test_allowed_but_unregistered_tool_is_not_executed(self) -> None:
        guard = Guard(_contract_dict(), semantic=False)
        result = guard.check("check_balance")
        assert result.allowed and not result.executed and result.output is None

    def test_tool_exception_is_reported_not_raised(self) -> None:
        guard = Guard(_contract_dict(), semantic=False, tools={"check_balance": lambda: 1 / 0})
        result = guard.check("check_balance")
        assert result.allowed and not result.executed
        assert result.error and "division" in result.error

    def test_semantic_check_runs_ids(self) -> None:
        guard = Guard(_contract_dict())
        guard.register("check_balance", lambda: {"balance": 1})
        result = guard.check("check_balance", message="what is my balance")
        assert result.decision in ("PASS", "PREEMPTIVE_WARN", "NEEDS_RECOVERY", "BLOCK")
        assert 0.0 <= result.ids_score <= 1.0
        assert result.allowed == (result.decision in ("PASS", "PREEMPTIVE_WARN"))

    def test_repr_is_readable(self) -> None:
        guard, _ = self._guard()
        text = repr(guard.check("admin_login"))
        assert text.startswith("GuardResult(allowed=False, decision=BLOCK")
        assert "reason=forbidden_tool" in text


# ── thresholds and config loading ───────────────────────────────────────────


class TestThresholdsAndConfig:
    def test_contract_thresholds_are_used(self) -> None:
        guard = Guard(_contract_dict(ids_warn_threshold=0.8, ids_block_threshold=0.95))
        assert guard.engine.ids_warn_threshold == 0.8
        assert guard.engine.ids_block_threshold == 0.95

        contract = RMICContract.create(
            **_contract_dict(ids_warn_threshold=0.8, ids_block_threshold=0.95),
            require_embedding=False,
        )
        engine = EnforcementEngine(contract=contract, tools=ToolRegistry())
        assert (engine.ids_warn_threshold, engine.ids_block_threshold) == (0.8, 0.95)

    def test_config_yaml_in_cwd_has_no_effect(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "config.yaml").write_text(
            "thresholds:\n  warn_threshold: 0.11\n  block_threshold: 0.22\n"
            "ids:\n  weights:\n    role_distance: 1.0\n    semantic_grounding: 0.0\n"
            "    trajectory_curvature: 0.0\n"
        )
        monkeypatch.chdir(tmp_path)

        guard = Guard(_contract_dict(ids_warn_threshold=0.8, ids_block_threshold=0.95))
        assert guard.engine.ids_warn_threshold == 0.8
        assert guard.engine.ids_block_threshold == 0.95
        assert rmic_config.load_user_config() == {}
        assert rmic_config.load_config()["ids"]["weights"]["semantic_grounding"] == 0.4

        # A contract without thresholds falls back to built-in defaults, not cwd config.
        default_guard = Guard(_contract_dict(), semantic=False)
        assert default_guard.engine.ids_warn_threshold == 0.35
        assert default_guard.engine.ids_block_threshold == 0.60

    def test_explicit_rmic_config_overrides(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "rmic.yaml"
        cfg.write_text("thresholds:\n  warn_threshold: 0.5\n")
        monkeypatch.setenv("RMIC_CONFIG", str(cfg))

        guard = Guard(_contract_dict(ids_warn_threshold=0.8, ids_block_threshold=0.95))
        assert guard.engine.ids_warn_threshold == 0.5  # explicitly configured
        assert guard.engine.ids_block_threshold == 0.95  # not configured -> contract

    def test_explicit_missing_config_is_an_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RMIC_CONFIG", str(tmp_path / "nope.yaml"))
        with pytest.raises(FileNotFoundError):
            rmic_config.load_config()


# ── session memory ──────────────────────────────────────────────────────────


class _EngineSpy:
    def __init__(self, guard: Guard) -> None:
        self.calls: list[dict[str, Any]] = []
        self._real = guard.engine.evaluate_and_maybe_execute
        guard.engine.evaluate_and_maybe_execute = self  # type: ignore[method-assign]

    def __call__(self, plan: PlannedToolCall, **kwargs: Any) -> EnforcementOutcome:
        self.calls.append(
            {
                "recent_ids": list(kwargs["recent_ids"]),
                "tool_call_history": list(kwargs["tool_call_history"]),
            }
        )
        return self._real(plan, **kwargs)


class TestSessions:
    def _guard(self) -> Guard:
        # Warn/block at 1.0 so every IDS score passes and the history keeps growing.
        guard = Guard(_contract_dict(ids_warn_threshold=1.0, ids_block_threshold=1.0))
        guard.register("check_balance", lambda: {"balance": 1})
        return guard

    def test_history_grows_and_reset_clears_it(self) -> None:
        guard = self._guard()
        spy = _EngineSpy(guard)

        for _ in range(3):
            guard.check("check_balance", message="balance please")

        assert [len(c["tool_call_history"]) for c in spy.calls] == [0, 1, 2]
        assert [len(c["recent_ids"]) for c in spy.calls] == [0, 1, 2]
        assert spy.calls[-1]["tool_call_history"] == ["check_balance", "check_balance"]
        assert len(guard.ids_history) == 3 and len(guard.tool_history) == 3

        guard.reset()
        assert guard.ids_history == () and guard.tool_history == ()
        guard.check("check_balance")
        assert spy.calls[-1]["recent_ids"] == [] and spy.calls[-1]["tool_call_history"] == []

    def test_sessions_are_isolated(self) -> None:
        guard = self._guard()
        spy = _EngineSpy(guard)
        alice, bob = guard.session("alice"), guard.session("bob")

        alice.check("check_balance")
        alice.check("check_balance")
        bob.check("check_balance")

        assert spy.calls[-1]["tool_call_history"] == []  # bob saw none of alice's calls
        assert len(alice.tool_history) == 2 and len(bob.tool_history) == 1
        assert guard.tool_history == ()  # default session untouched
        assert len(guard.session("alice").tool_history) == 2  # same id -> same history

        alice.reset()
        assert alice.tool_history == () and len(bob.tool_history) == 1

    def test_blocked_calls_are_part_of_history(self) -> None:
        guard = Guard(_contract_dict(), semantic=False)
        guard.check("admin_login")
        assert guard.tool_history == ("admin_login",)
        assert guard.ids_history == ()  # no IDS in hard-rules-only mode


# ── run() with a stub reasoning backend ─────────────────────────────────────


class _StubBackend:
    def __init__(self, plans: list[PlannedToolCall]) -> None:
        self.plans = list(plans)
        self.calls: list[dict[str, Any]] = []

    def plan_tool_call(self, user_message: str, **kwargs: Any) -> PlannedToolCall:
        self.calls.append({"user_message": user_message, **kwargs})
        return self.plans[min(len(self.calls), len(self.plans)) - 1]


def _plan(tool: str = "check_balance", **arguments: Any) -> PlannedToolCall:
    return PlannedToolCall(tool_name=tool, arguments=arguments, raw_text=f"call {tool}")


class TestRun:
    def test_needs_recovery_triggers_exactly_one_replan_then_blocks(self) -> None:
        # warn=0.0: every plan lands in the warn zone, so recovery can't succeed.
        guard = Guard(_contract_dict(ids_warn_threshold=0.0, ids_block_threshold=1.0))
        calls: list[str] = []
        guard.register("check_balance", lambda: calls.append("ran"))
        backend = _StubBackend([_plan(), _plan()])

        result = guard.run("what's my balance?", llm=backend)

        assert len(backend.calls) == 2  # initial plan + exactly one re-plan
        first, retry = backend.calls
        assert first.get("extra_system") is None
        assert retry["extra_system"] and "identity contract" in retry["extra_system"]
        assert retry["user_message"].startswith("what's my balance?")
        assert "RMIC recovery" in retry["user_message"]
        assert not result.allowed and result.decision == "BLOCK"
        assert result.recovery_attempted
        assert result.reason == "recovery_failed:ids_warn_threshold_reached"
        assert calls == []

    def test_successful_recovery_executes_the_replanned_tool(self) -> None:
        guard = Guard(_contract_dict(ids_warn_threshold=1.0, ids_block_threshold=1.0))
        guard.register("check_balance", lambda: {"balance": 7})
        real = guard.engine.evaluate_and_maybe_execute
        seen: list[str] = []

        def first_needs_recovery(plan: PlannedToolCall, **kwargs: Any) -> EnforcementOutcome:
            seen.append(plan.tool_name)
            if len(seen) == 1:
                return EnforcementOutcome(
                    decision="NEEDS_RECOVERY", ids_score=0.5, drift_velocity=0.0,
                    ids_components=None, hard_rule_violation=None,
                    recovery_system_message="re-anchor", recovery_user_message="try again",
                    tool_result=None,
                )
            return real(plan, **kwargs)

        guard.engine.evaluate_and_maybe_execute = first_needs_recovery  # type: ignore[method-assign]
        backend = _StubBackend([_plan(), _plan()])

        result = guard.run("balance?", llm=backend)

        assert len(backend.calls) == 2
        assert backend.calls[1]["extra_system"] == "re-anchor"
        assert result.allowed and result.recovery_attempted
        assert result.output == {"balance": 7}

    def test_max_recovery_zero_blocks_without_replanning(self) -> None:
        guard = Guard(_contract_dict(ids_warn_threshold=0.0, ids_block_threshold=1.0))
        backend = _StubBackend([_plan()])
        result = guard.run("balance?", llm=backend, max_recovery=0)
        assert len(backend.calls) == 1
        assert result.decision == "BLOCK" and not result.recovery_attempted

    def test_hard_rule_block_does_not_replan(self) -> None:
        guard = Guard(_contract_dict(), semantic=False)
        backend = _StubBackend([_plan("admin_login")])
        result = guard.run("log me in as admin", llm=backend)
        assert len(backend.calls) == 1
        assert result.decision == "BLOCK" and result.reason == "forbidden_tool"

    def test_unknown_llm_string_is_rejected(self) -> None:
        guard = Guard(_contract_dict(), semantic=False)
        with pytest.raises((ValueError, ImportError)):
            guard.run("hi", llm="someprovider/model")


# ── audit log ───────────────────────────────────────────────────────────────


class TestAudit:
    def test_log_verifies_across_restarts_and_detects_edits(self, tmp_path: Path) -> None:
        log, key = tmp_path / "audit.jsonl", tmp_path / "audit.key"

        guard = Guard(_contract_dict(), semantic=False, audit_log=log, audit_key=key)
        guard.register("check_balance", lambda: 1)
        guard.check("check_balance")
        guard.check("admin_login")
        assert key.is_file() and Path(str(log) + ".pub").is_file()

        # "Restart": a brand-new Guard and ledger reusing the same key file.
        guard2 = Guard(_contract_dict(), semantic=False, audit_log=log, audit_key=key)
        guard2.check("admin_login")
        assert guard2.verify_log() is True
        assert AuditLedger(log, key_path=key).verify() is True
        assert AuditLedger.verify_file(log) is True

        lines = log.read_text().splitlines()
        assert len(lines) == 3
        tampered = json.loads(lines[1])
        tampered["entry"]["decision"] = "PASS"
        lines[1] = json.dumps(tampered, separators=(",", ":"))
        log.write_text("\n".join(lines) + "\n")

        assert guard2.verify_log() is False
        assert AuditLedger.verify_file(log) is False

    def test_default_key_file_is_created_next_to_log_and_reused(self, tmp_path: Path) -> None:
        log = tmp_path / "logs" / "audit.jsonl"
        first = AuditLedger(log)
        key_path = Path(str(log) + ".key")
        assert first.key_path == key_path and key_path.is_file()
        if os.name == "posix":
            assert (key_path.stat().st_mode & 0o777) == 0o600

        second = AuditLedger(log)
        assert second.public_key_bytes() == first.public_key_bytes()

    def test_key_from_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = tmp_path / "env.key"
        monkeypatch.setenv("RMIC_AUDIT_KEY", str(key))
        a = AuditLedger(tmp_path / "a.jsonl")
        b = AuditLedger(tmp_path / "b.jsonl")
        assert a.key_path == key and a.public_key_bytes() == b.public_key_bytes()

    def test_mismatched_key_for_existing_log_is_refused(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.jsonl"
        AuditLedger(log, key_path=tmp_path / "one.key")
        with pytest.raises(ValueError, match="different public key"):
            AuditLedger(log, key_path=tmp_path / "two.key")

    def test_verify_log_without_audit_log_raises(self) -> None:
        with pytest.raises(RMICGuardError):
            Guard(_contract_dict(), semantic=False).verify_log()


# ── no embedding backend installed ──────────────────────────────────────────


@pytest.fixture
def no_embedding_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate an install where neither fastembed nor sentence-transformers exists."""
    monkeypatch.setattr(embedder, "_embedding_backend", None)
    monkeypatch.setitem(sys.modules, "fastembed", None)
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    embedder.get_model.cache_clear()
    yield
    embedder.get_model.cache_clear()


class TestNoEmbeddingBackend:
    def test_semantic_false_works_without_any_backend(self, tmp_path: Path, no_embedding_backend: None) -> None:
        path = _write(tmp_path / "bot.json", _contract_dict())
        guard = Guard(path, semantic=False)
        guard.register("check_balance", lambda: {"balance": 100})
        assert guard.check("check_balance").decision == "PASS"
        assert guard.check("admin_login").decision == "BLOCK"

    def test_semantic_true_gives_clear_error(self, no_embedding_backend: None) -> None:
        with pytest.raises(RMICGuardError, match=r"semantic=False") as excinfo:
            Guard(_contract_dict())
        assert "rmic-guard[torch]" in str(excinfo.value)
        assert not isinstance(excinfo.value, ModuleNotFoundError)


# ── packaging: no top-level `utils` / `core` collision ──────────────────────


def test_import_succeeds_next_to_user_utils_and_config(tmp_path: Path) -> None:
    (tmp_path / "utils.py").write_text("VALUE = 1\n")
    (tmp_path / "core.py").write_text("VALUE = 2\n")
    (tmp_path / "config.yaml").write_text("thresholds:\n  warn_threshold: 0.01\n")
    env = dict(os.environ)
    env.pop("RMIC_CONFIG", None)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(REPO_ROOT), env.get("PYTHONPATH", "")) if p)
    code = (
        "import utils, rmic_guard\n"
        "from rmic_guard import Guard\n"
        "assert utils.VALUE == 1\n"
        "g = Guard({'agent_id': 'bot', 'role_name': 'Bot', 'sector': 'demo',"
        " 'semantic_anchors': ['I check balances.'], 'allowed_actions': ['check_balance']},"
        " semantic=False)\n"
        "assert g.engine.ids_warn_threshold == 0.35, g.engine.ids_warn_threshold\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"
