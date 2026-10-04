from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from simo.approvals import ApprovalError, ApprovalService
from simo.db import SimoDatabase, StoreError
from simo.policy import SimoTool, SimoToolRegistry, ToolClass, ToolContext


def seed(database: SimoDatabase) -> None:
    database.create_teacher("teacher-1")
    database.create_class("teacher-1", "class-1", "Synthetic")
    database.save_artifact("teacher-1", "class-1", "artifact-1", "feedback", "Synthetic draft")


def test_allowlist_and_teacher_mutation_checks_precede_handler(tmp_path) -> None:
    database = SimoDatabase(tmp_path / "simo.sqlite")
    try:
        seed(database)
        calls: list[str] = []
        registry = SimoToolRegistry(database, [
            SimoTool("write_local", ToolClass.WRITE_LOCAL, lambda args, ctx: calls.append("ran")),
        ])
        stranger = ToolContext("teacher-1", "class-1", False)
        assert registry.execute("shell", {}, stranger)["status"] == "denied"
        assert registry.execute("write_local", {}, stranger)["status"] == "denied"
        assert calls == []
        trace = database.list_events("teacher-1", "class-1", kind="policy_decision")
        assert [row["payload"]["decision"] for row in trace] == ["deny", "deny"]
        assert "args" not in trace[0]["payload"]
        teacher = ToolContext("teacher-1", "class-1", True)
        assert registry.execute("write_local", {}, teacher)["status"] == "completed"
        assert calls == ["ran"]
    finally:
        database.close()


def test_release_requires_valid_one_time_hash_bound_approval(tmp_path) -> None:
    database = SimoDatabase(tmp_path / "simo.sqlite")
    try:
        seed(database)
        service = ApprovalService(database, "a" * 32)
        released: list[str] = []
        registry = SimoToolRegistry(database, [
            SimoTool("release_artifact", ToolClass.RELEASE,
                     lambda args, ctx: released.append(args["artifact_id"])),
        ])
        teacher = ToolContext("teacher-1", "class-1", True)
        assert registry.execute("release_artifact", {"artifact_id": "artifact-1"}, teacher)["status"] == "needs_approval"
        approval_id, token = service.request_release("teacher-1", "class-1", "artifact-1")
        with pytest.raises(ApprovalError, match="authenticator"):
            service.resolve("teacher-1", "class-1", approval_id, "bad", approve=True)
        service.resolve("teacher-1", "class-1", approval_id, token, approve=True)
        assert registry.execute("release_artifact", {"artifact_id": "artifact-1"}, teacher)["status"] == "completed"
        assert released == ["artifact-1"]
        with pytest.raises(ApprovalError, match="resolved"):
            service.resolve("teacher-1", "class-1", approval_id, token, approve=True)
        database.update_artifact("teacher-1", "class-1", "artifact-1", "Edited draft")
        assert registry.execute("release_artifact", {"artifact_id": "artifact-1"}, teacher)["status"] == "needs_approval"
        assert released == ["artifact-1"]
    finally:
        database.close()


def test_expired_and_cross_tenant_approvals_cannot_resolve(tmp_path) -> None:
    database = SimoDatabase(tmp_path / "simo.sqlite")
    try:
        seed(database)
        database.create_teacher("teacher-2")
        database.create_class("teacher-2", "class-1", "Other synthetic class")
        service = ApprovalService(database, "b" * 32)
        expired = datetime.now(UTC) - timedelta(seconds=1)
        database.create_approval("teacher-1", "class-1", "expired", "artifact-1", "release",
                                 "nonce", expired.isoformat())
        with pytest.raises(ApprovalError, match="expired"):
            service.resolve("teacher-1", "class-1", "expired", "unused", approve=True)
        with pytest.raises(StoreError, match="scope"):
            service.request_release("teacher-2", "class-1", "artifact-1")
    finally:
        database.close()
