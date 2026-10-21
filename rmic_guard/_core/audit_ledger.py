"""Append-only audit ledger with per-entry Ed25519 signatures and a hash chain.

Each line stores the SHA-256 of the line before it (``prev_hash``) inside
its signed payload, so verify_file() detects edited, deleted, inserted and
reordered lines, not only forged ones.

The signing key is persistent so a log can be verified after a restart:

  1. an explicit ``private_key`` object, else
  2. the PEM key file at ``key_path``, else
  3. the PEM key file named by the ``RMIC_AUDIT_KEY`` environment variable, else
  4. ``<log>.key`` next to the log.

A key file that does not exist yet is generated (owner read/write only,
0600). The matching public key is written to ``<log>.pub`` so anyone can
check the log with ``AuditLedger.verify_file(<log>)`` without the private key.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

__all__ = ["AUDIT_KEY_ENV_VAR", "AuditEntry", "AuditLedger"]

AUDIT_KEY_ENV_VAR = "RMIC_AUDIT_KEY"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AuditEntry:
    timestamp: str
    agent_id: str
    input_hash: str
    ids_score: float
    drift_type: str | None
    drift_velocity: float | None
    decision: str
    contract_hash: str
    recovery_attempted: bool
    role_distance: float | None = None
    semantic_grounding: float | None = None
    trajectory_curvature: float | None = None
    failure_reason: str | None = None
    false_positive: bool = False
    false_negative: bool = False
    # Links a NEEDS_CONFIRMATION entry to the CONFIRMED entry that executed it.
    confirmation_id: str | None = None


GENESIS_HASH = "0" * 64


def line_hash(line: str) -> str:
    """SHA-256 of one log line, ignoring its trailing newline / CRLF."""
    return sha256(line.rstrip("\r\n").encode("utf-8")).hexdigest()


def _signed_payload(entry: Mapping[str, Any], prev_hash: str) -> bytes:
    return json.dumps(
        {"entry": entry, "prev_hash": prev_hash}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sidecar(path: Path, suffix: str) -> Path:
    return path.with_name(path.name + suffix)


def _load_or_create_private_key(key_path: Path) -> Ed25519PrivateKey:
    if key_path.is_file():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(f"{key_path} does not contain an Ed25519 private key")
        return key
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL: never clobber a key another process created in the meantime.
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return key


def _public_pem(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


class AuditLedger:
    """
    Append-only, hash-chained JSONL ledger. Each line is a JSON object:
    { "entry": {...}, "prev_hash": "<sha256 hex of previous line>", "signature": "<base64>" }
    The signature covers entry + prev_hash; the first line's prev_hash is GENESIS_HASH.
    """

    def __init__(
        self,
        path: str | Path,
        private_key: Ed25519PrivateKey | None = None,
        *,
        key_path: str | Path | None = None,
    ) -> None:
        self.path = Path(path)
        if private_key is not None:
            self.key_path: Path | None = None
            self._private_key = private_key
        else:
            env_key = (os.environ.get(AUDIT_KEY_ENV_VAR) or "").strip()
            self.key_path = Path(key_path or env_key or _sidecar(self.path, ".key"))
            self._private_key = _load_or_create_private_key(self.key_path)
        self._public_key = self._private_key.public_key()
        self._write_public_key()

    @property
    def public_key_path(self) -> Path:
        return _sidecar(self.path, ".pub")

    def _write_public_key(self) -> None:
        pem = _public_pem(self._public_key)
        pub_path = self.public_key_path
        if pub_path.is_file():
            if pub_path.read_bytes().strip() != pem.strip():
                raise ValueError(
                    f"{pub_path} holds a different public key than the signing key in use, so "
                    f"existing entries in {self.path} could no longer be verified. Use the "
                    "original key (audit_key / RMIC_AUDIT_KEY) or a new log path."
                )
            return
        pub_path.parent.mkdir(parents=True, exist_ok=True)
        pub_path.write_bytes(pem)

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._public_key

    def public_key_bytes(self) -> bytes:
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def _last_line_hash(self) -> str:
        """Hash of the last non-empty line already in the log (GENESIS_HASH if none)."""
        if not self.path.is_file():
            return GENESIS_HASH
        last = ""
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
        return line_hash(last) if last else GENESIS_HASH

    def append(self, entry: AuditEntry) -> None:
        """Sign and append ``entry``, chained to the previous line via prev_hash.

        The chain is read from the file on every append, so a fresh process
        (or a second AuditLedger on the same path) continues it correctly.
        Concurrent writers to one log file are not supported.
        """
        prev_hash = self._last_line_hash()
        sig = self._private_key.sign(_signed_payload(asdict(entry), prev_hash))
        line = json.dumps(
            {
                "entry": asdict(entry),
                "prev_hash": prev_hash,
                "signature": base64.b64encode(sig).decode("ascii"),
            },
            separators=(",", ":"),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def verify(self) -> bool:
        """Verify every entry of this ledger's log with its public key."""
        return self.verify_file(self.path, public_key=self._public_key)

    @staticmethod
    def verify_line(line: str, public_key: Ed25519PublicKey) -> bool:
        """Check one line's signature (chained or pre-chaining format)."""
        obj = json.loads(line)
        sig = base64.b64decode(obj["signature"])
        if "prev_hash" in obj:
            payload = _signed_payload(obj["entry"], obj["prev_hash"])
        else:  # lines written before hash chaining: signature over the entry only
            payload = json.dumps(obj["entry"], sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            public_key.verify(sig, payload)
        except Exception:
            return False
        return True

    @staticmethod
    def verify_file(path: str | Path, public_key: Ed25519PublicKey | None = None) -> bool:
        """Return True iff the log at ``path`` is intact.

        Every line must carry a valid signature AND a prev_hash equal to the
        SHA-256 of the line before it (GENESIS_HASH for the first line), so
        edited, forged, deleted, inserted and reordered lines are all
        detected. Removing lines from the *end* of the log leaves a valid
        shorter chain; to detect that, record ``AuditLedger.head_hash(path)``
        somewhere outside the log and compare. The public key defaults to the
        ``<log>.pub`` file written alongside the log. Malformed lines and
        lines without a prev_hash count as failures.
        """
        log_path = Path(path)
        if public_key is None:
            pub_path = _sidecar(log_path, ".pub")
            loaded = serialization.load_pem_public_key(pub_path.read_bytes())
            if not isinstance(loaded, Ed25519PublicKey):
                raise ValueError(f"{pub_path} does not contain an Ed25519 public key")
            public_key = loaded
        if not log_path.is_file():
            return False
        expected_prev = GENESIS_HASH
        with log_path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    if json.loads(line).get("prev_hash") != expected_prev:
                        return False
                    if not AuditLedger.verify_line(line, public_key):
                        return False
                except (ValueError, KeyError, TypeError, AttributeError):
                    return False
                expected_prev = line_hash(line)
        return True

    @staticmethod
    def head_hash(path: str | Path) -> str:
        """Hash of the log's last line: store it externally to detect tail truncation."""
        last = ""
        with Path(path).open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
        return line_hash(last) if last else GENESIS_HASH


def hash_text(text: str) -> str:
    """SHA-256 hex digest of UTF-8 text (for input_hash)."""
    return sha256(text.encode("utf-8")).hexdigest()


def entry_from_mapping(m: Mapping[str, Any]) -> AuditEntry:
    return AuditEntry(
        timestamp=str(m["timestamp"]),
        agent_id=str(m["agent_id"]),
        input_hash=str(m["input_hash"]),
        ids_score=float(m["ids_score"]),
        role_distance=None if m.get("role_distance") is None else float(m["role_distance"]),
        semantic_grounding=(
            None if m.get("semantic_grounding") is None else float(m["semantic_grounding"])
        ),
        trajectory_curvature=(
            None if m.get("trajectory_curvature") is None else float(m["trajectory_curvature"])
        ),
        drift_type=m.get("drift_type"),
        drift_velocity=None if m.get("drift_velocity") is None else float(m["drift_velocity"]),
        decision=str(m["decision"]),
        failure_reason=(None if m.get("failure_reason") is None else str(m.get("failure_reason"))),
        false_positive=bool(m.get("false_positive", False)),
        false_negative=bool(m.get("false_negative", False)),
        contract_hash=str(m["contract_hash"]),
        recovery_attempted=bool(m["recovery_attempted"]),
        confirmation_id=None if m.get("confirmation_id") is None else str(m["confirmation_id"]),
    )
