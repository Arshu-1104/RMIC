"""Append-only audit ledger with per-entry Ed25519 signatures.

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
    Append-only JSONL ledger. Each line is a JSON object:
    { "entry": {...}, "signature": "<base64>" }
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

    def append(self, entry: AuditEntry) -> None:
        payload = json.dumps(asdict(entry), sort_keys=True, separators=(",", ":")).encode("utf-8")
        sig = self._private_key.sign(payload)
        line = json.dumps(
            {
                "entry": asdict(entry),
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
        obj = json.loads(line)
        entry = obj["entry"]
        sig = base64.b64decode(obj["signature"])
        payload = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            public_key.verify(sig, payload)
        except Exception:
            return False
        return True

    @staticmethod
    def verify_file(path: str | Path, public_key: Ed25519PublicKey | None = None) -> bool:
        """Return True iff every line of the log at ``path`` carries a valid signature.

        The public key defaults to the ``<log>.pub`` file written alongside the
        log. Malformed lines count as failures. Note that signatures are
        per-entry: this detects edited or forged entries, not deleted ones.
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
        with log_path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    if not AuditLedger.verify_line(line, public_key):
                        return False
                except (ValueError, KeyError, TypeError):
                    return False
        return True


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
    )
