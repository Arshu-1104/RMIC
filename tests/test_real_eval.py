"""Real-data evaluation tooling: dataset checksum verification and the pre-registered
Banking77 intent -> tool mapping. Uses a tiny invented fixture; never the real datasets."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from rmic_guard import Guard, load_example_contract

REPO = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_eval" / "banking77_sample.csv"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fetch = _load("fetch_real_eval_data", REPO / "scripts" / "fetch_real_eval_data.py")
mapping = _load("real_eval_mapping", REPO / "experiment" / "eval_real_data" / "mapping.py")


# ── fetch_real_eval_data.py ─────────────────────────────────────────────────


class TestFetchChecksums:
    BODY = b"text,category\nhello,card_arrival\n"
    FILES = {"banking77/train.csv": ("https://example.invalid/train.csv", hashlib.sha256(BODY).hexdigest())}

    def test_matching_download_is_written(self, tmp_path: Path) -> None:
        urls: list[str] = []
        paths = fetch.fetch(tmp_path, self.FILES, download=lambda url: urls.append(url) or self.BODY)
        assert paths == [tmp_path / "banking77" / "train.csv"]
        assert paths[0].read_bytes() == self.BODY and urls == ["https://example.invalid/train.csv"]

    def test_mismatching_download_raises_and_writes_nothing(self, tmp_path: Path) -> None:
        with pytest.raises(fetch.ChecksumError, match="does not match the pinned"):
            fetch.fetch(tmp_path, self.FILES, download=lambda url: self.BODY + b"tampered")
        assert not (tmp_path / "banking77" / "train.csv").exists()

    def test_verified_local_copy_is_not_downloaded_again(self, tmp_path: Path) -> None:
        (tmp_path / "banking77").mkdir()
        (tmp_path / "banking77" / "train.csv").write_bytes(self.BODY)
        fetch.fetch(tmp_path, self.FILES, download=lambda url: pytest.fail("downloaded a verified file"))

    def test_corrupted_local_copy_is_replaced(self, tmp_path: Path) -> None:
        (tmp_path / "banking77").mkdir()
        (tmp_path / "banking77" / "train.csv").write_bytes(b"corrupted")
        fetch.fetch(tmp_path, self.FILES, download=lambda url: self.BODY)
        assert (tmp_path / "banking77" / "train.csv").read_bytes() == self.BODY

    def test_every_pinned_file_has_a_sha256_and_a_pinned_url(self) -> None:
        assert len(fetch.FILES) == 6
        for rel, (url, digest) in fetch.FILES.items():
            assert len(digest) == 64 and int(digest, 16) >= 0, rel
            assert fetch.GANDALF_REVISION in url or fetch.BANKING77_COMMIT in url, rel

    def test_real_eval_data_is_git_ignored(self) -> None:
        assert "data/real_eval/" in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()


# ── mapping.py ──────────────────────────────────────────────────────────────


def _fixture_rows() -> list[dict[str, str]]:
    with open(FIXTURE, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class TestIntentMapping:
    @pytest.mark.parametrize(
        "intent, tool",
        [
            ("transfer_timing", "transfer_funds"),
            ("top_up_failed", "transfer_funds"),
            ("topping_up_by_card", "transfer_funds"),
            ("balance_not_updated_after_bank_transfer", "check_balance"),  # "balance" wins over "transfer"
            ("card_swallowed", "check_balance"),  # no support tool in the contract
            ("beneficiary_not_allowed", "check_balance"),
        ],
    )
    def test_tool_for_intent(self, intent: str, tool: str) -> None:
        assert mapping.tool_for_intent(intent) == tool

    def test_fixture_rows_map_to_contract_tools_with_valid_arguments(self) -> None:
        rows = _fixture_rows()
        calls = mapping.banking_calls(r["category"] for r in rows)
        assert [t for t, _ in calls] == ["transfer_funds", "transfer_funds", "check_balance", "check_balance",
                                         "check_balance", "transfer_funds"]
        guard = Guard(load_example_contract("financial_agent_hardened"))
        for k, (row, (tool, args)) in enumerate(zip(rows, calls)):
            if tool == "transfer_funds":
                assert set(args) == {"amount", "to_account"} and 0.01 <= args["amount"] < 50_000
            else:
                assert args == {}
            r = guard.session(str(k)).check(tool, message=row["text"], arguments=args)
            assert r.decision in ("PASS", "NEEDS_CONFIRMATION"), (row, r)

    def test_draws_are_seeded_and_independent_of_the_mapping(self) -> None:
        first = list(mapping.draws(1000))
        assert first == list(mapping.draws(1000))
        assert list(mapping.draws(1000, seed=7)) != first
        amounts = sorted(a for a, _ in first)
        assert 1100 < amounts[500] < 2000  # median near 1,500
        assert max(amounts) <= mapping.AMOUNT_CAP and min(amounts) >= 0.01
        assert all(len(acct) == 8 and acct.isdigit() for _, acct in first)
        # Transfer rows get the same draw whatever the other rows map to.
        a = mapping.banking_calls(["transfer_timing", "card_arrival", "transfer_timing"])
        b = mapping.banking_calls(["transfer_timing", "transfer_timing", "transfer_timing"])
        assert a[0] == b[0] and a[2] == b[2]

    def test_every_mapped_tool_is_allowed_by_the_contract(self) -> None:
        allowed = set(load_example_contract("financial_agent_hardened").allowed_actions)
        intents = [r["category"] for r in _fixture_rows()]
        assert {mapping.tool_for_intent(i) for i in intents} <= allowed
        assert {t for t, _ in mapping.gandalf_calls()} <= allowed

    def test_gandalf_actions_are_allowed_and_in_limit(self) -> None:
        guard = Guard(load_example_contract("financial_agent_hardened"))
        for k, (tool, args) in enumerate(mapping.gandalf_calls()):
            assert guard.session(str(k)).check(tool, message="", arguments=args).decision == "PASS"

    def test_plan_table_matches_the_code(self) -> None:
        plan = (REPO / "experiment" / "eval_real_data" / "PLAN.md").read_text(encoding="utf-8")
        for line in plan.splitlines():
            if line.startswith("| transfer / top-up") or line.startswith("| balance") or line.startswith("| other"):
                tool = line.split("|")[2].strip().strip("`")
                for intent in line.split("|")[3].split(","):
                    assert mapping.tool_for_intent(intent.strip()) == tool, intent
        assert json.dumps(mapping.SEED) == "42"
