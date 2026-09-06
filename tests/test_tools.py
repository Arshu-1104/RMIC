from __future__ import annotations

from core.tool_layer import ToolRegistry


class TestRegisterAndRetrieve:
    def test_register_then_has(self) -> None:
        reg = ToolRegistry()
        reg.register("web_search", lambda query: {"ok": True})
        assert reg.has("web_search") is True

    def test_has_false_for_unregistered(self) -> None:
        reg = ToolRegistry()
        assert reg.has("nope") is False

    def test_execute_registered_tool_with_valid_token(self) -> None:
        reg = ToolRegistry()
        reg.register("echo", lambda value: value)
        token = reg.issue_approval_token()
        result = reg.execute("echo", approval_token=token, value=42)
        assert result.ok is True
        assert result.data == 42
        assert result.error is None


class TestUnknownTool:
    def test_execute_unknown_tool_returns_error_result(self) -> None:
        reg = ToolRegistry()
        token = reg.issue_approval_token()
        result = reg.execute("does_not_exist", approval_token=token)
        assert result.ok is False
        assert result.error == "unknown_tool:does_not_exist"


class TestDuplicateRegistration:
    def test_duplicate_registration_overwrites(self) -> None:
        reg = ToolRegistry()
        reg.register("t", lambda: "first")
        reg.register("t", lambda: "second")
        token = reg.issue_approval_token()
        result = reg.execute("t", approval_token=token)
        assert result.data == "second"


class TestApprovalTokenGate:
    def test_execute_without_valid_token_is_rejected(self) -> None:
        reg = ToolRegistry()
        reg.register("t", lambda: "ran")
        result = reg.execute("t", approval_token="wrong-token")
        assert result.ok is False
        assert result.error == "execution_not_approved_by_enforcement_engine"

    def test_execute_without_any_token_is_rejected(self) -> None:
        reg = ToolRegistry()
        reg.register("t", lambda: "ran")
        result = reg.execute("t")
        assert result.ok is False

    def test_tool_raising_exception_is_captured_as_error_result(self) -> None:
        reg = ToolRegistry()

        def boom() -> None:
            raise ValueError("kaboom")

        reg.register("boom", boom)
        token = reg.issue_approval_token()
        result = reg.execute("boom", approval_token=token)
        assert result.ok is False
        assert "kaboom" in (result.error or "")
