"""Out-of-band, one-use HMAC approval capabilities."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from simo.db import SimoDatabase


class ApprovalError(ValueError):
    """Approval token is invalid, expired, or already used."""


class ApprovalService:
    def __init__(self, database: SimoDatabase, secret: str | bytes) -> None:
        key = secret.encode() if isinstance(secret, str) else secret
        if len(key) < 32:
            raise ValueError("approval secret must contain at least 32 bytes")
        self.database = database
        self._key = key

    def request_release(
        self, teacher_id: str, class_id: str, artifact_id: str, *, ttl: timedelta = timedelta(hours=24),
    ) -> tuple[str, str]:
        if ttl.total_seconds() <= 0:
            raise ValueError("approval lifetime must be positive")
        approval_id, nonce = uuid.uuid4().hex, secrets.token_urlsafe(24)
        self.database.create_approval(
            teacher_id, class_id, approval_id, artifact_id, "release", nonce,
            (datetime.now(UTC) + ttl).isoformat(),
        )
        message = f"{teacher_id}\0{class_id}\0{approval_id}\0{nonce}".encode()
        token = hmac.new(self._key, message, hashlib.sha256).hexdigest()
        return approval_id, token

    def resolve(self, teacher_id: str, class_id: str, approval_id: str, token: str, *, approve: bool) -> None:
        # Resolve only after validating HMAC against the nonce stored for this scoped pending approval.
        row = self.database.get_pending_approval(teacher_id, class_id, approval_id)
        if row is None or row["expires_at"] <= datetime.now(UTC).isoformat():
            raise ApprovalError("approval is missing, expired, or already resolved")
        message = f"{teacher_id}\0{class_id}\0{approval_id}\0{row['nonce']}".encode()
        expected = hmac.new(self._key, message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, token):
            raise ApprovalError("invalid approval authenticator")
        if not self.database.resolve_approval(
            teacher_id, class_id, approval_id, row["nonce"], "approved" if approve else "rejected",
        ):
            raise ApprovalError("approval has already been resolved")

