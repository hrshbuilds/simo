"""Nanobot tools exposing the synthetic teacher workflow demo."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.bus.events import OutboundMessage

from simo.teacher_demo import TeacherDemoStore


class _TeacherDemoTool(Tool):
    def __init__(self, workspace: str) -> None:
        self.workspace = Path(workspace)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(ctx.workspace)

    def _store(self) -> TeacherDemoStore:
        workspace_data = self.workspace / "demo" / "teacher_data.json"
        bundled_data = Path(__file__).resolve().parent.parent / "demo" / "teacher_data.json"
        data_path = workspace_data if workspace_data.exists() else bundled_data
        return TeacherDemoStore(data_path)


@tool_parameters({
    "type": "object",
    "properties": {"class_id": {"type": "string", "description": "Demo class id, for example class-7a."}},
    "required": ["class_id"],
    "additionalProperties": False,
})
class TeacherClassOverviewTool(_TeacherDemoTool):
    @property
    def name(self) -> str:
        return "teacher_class_overview"

    @property
    def description(self) -> str:
        return "Read the synthetic class summary, marks average, assignments, and attention list."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, class_id: str) -> Any:
        return self._store().overview(class_id)


@tool_parameters({
    "type": "object",
    "properties": {"class_id": {"type": "string", "description": "Demo class id, for example class-7a."}},
    "required": ["class_id"],
    "additionalProperties": False,
})
class TeacherMissingWorkTool(_TeacherDemoTool):
    @property
    def name(self) -> str:
        return "teacher_missing_work"

    @property
    def description(self) -> str:
        return "List synthetic students with missing assignments."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, class_id: str) -> Any:
        return self._store().missing_work(class_id)


@tool_parameters({
    "type": "object",
    "properties": {"class_id": {"type": "string", "description": "Demo class id, for example class-7a."}},
    "required": ["class_id"],
    "additionalProperties": False,
})
class TeacherWeeklyReportTool(_TeacherDemoTool):
    @property
    def name(self) -> str:
        return "teacher_weekly_report"

    @property
    def description(self) -> str:
        return "Prepare a synthetic weekly teaching report; it does not send or publish anything."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, class_id: str) -> Any:
        return self._store().weekly_report(class_id)


@tool_parameters({
    "type": "object",
    "properties": {
        "class_id": {"type": "string", "description": "Demo class id, for example class-7a."},
        "student_id": {"type": "string", "description": "Demo student id, for example student-003."},
    },
    "required": ["class_id", "student_id"],
    "additionalProperties": False,
})
class TeacherMessageDraftTool(_TeacherDemoTool):
    @property
    def name(self) -> str:
        return "teacher_message_draft"

    @property
    def description(self) -> str:
        return "Draft a synthetic student message. Sending is never performed by this tool."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, class_id: str, student_id: str) -> Any:
        return self._store().draft_message(class_id, student_id)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_recipient(recipient: str) -> str:
    address = recipient.strip()
    if not _EMAIL_RE.fullmatch(address):
        raise ValueError("recipient must be a valid email address")
    return address


@tool_parameters({
    "type": "object",
    "properties": {
        "class_id": {"type": "string", "description": "Demo class id, for example class-7a."},
        "student_id": {"type": "string", "description": "Demo student id, for example student-003."},
        "recipient": {"type": "string", "description": "Email address to show in the draft."},
    },
    "required": ["class_id", "student_id", "recipient"],
    "additionalProperties": False,
})
class TeacherEmailDraftTool(_TeacherDemoTool):
    @property
    def name(self) -> str:
        return "teacher_email_draft"

    @property
    def description(self) -> str:
        return "Draft a supportive email for teacher review. This tool never sends email."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, class_id: str, student_id: str, recipient: str) -> Any:
        address = _validate_recipient(recipient)
        message = self._store().draft_message(class_id, student_id)
        return {
            "status": "draft_only",
            "to": address,
            "subject": f"Support with Science learning - {message['student_name']}",
            "body": message["message"],
            "approval_required": True,
            "send_instruction": "Reply with SEND EMAIL only after reviewing the recipient, subject, and body.",
        }


@tool_parameters({
    "type": "object",
    "properties": {
        "recipient": {"type": "string", "description": "Email address to send to."},
        "subject": {"type": "string", "description": "Reviewed email subject."},
        "body": {"type": "string", "description": "Reviewed email body."},
        "approval_phrase": {"type": "string", "description": "Must be exactly SEND EMAIL."},
    },
    "required": ["recipient", "subject", "body", "approval_phrase"],
    "additionalProperties": False,
})
class TeacherEmailSendTool(Tool):
    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(ctx)

    def __init__(self, context: ToolContext) -> None:
        self.context = context

    @property
    def name(self) -> str:
        return "teacher_email_send"

    @property
    def description(self) -> str:
        return "Send a reviewed email after explicit teacher approval with SEND EMAIL."

    @property
    def read_only(self) -> bool:
        return False

    async def execute(
        self, recipient: str, subject: str, body: str, approval_phrase: str,
    ) -> Any:
        address = _validate_recipient(recipient)
        request = current_request_context()
        original_text = (request.original_user_text if request else "") or ""
        if approval_phrase != "SEND EMAIL" or "SEND EMAIL" not in original_text.upper():
            return {
                "status": "approval_required",
                "message": "Email not sent. The teacher must explicitly reply SEND EMAIL after reviewing the draft.",
            }
        if self.context.bus is None:
            raise RuntimeError("email sending is unavailable because the message bus is not configured")
        await self.context.bus.publish_outbound(OutboundMessage(
            channel="email",
            chat_id=address,
            content=body,
            metadata={"subject": subject, "force_send": True, "teacher_approved": True},
        ))
        return {"status": "queued", "to": address, "subject": subject}
