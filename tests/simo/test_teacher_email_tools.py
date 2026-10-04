"""Tests for teacher email drafting and explicit send approval."""

from types import SimpleNamespace

import pytest

from nanobot.agent.tools.context import RequestContext, ToolContext, bind_request_context, reset_request_context
from nanobot.bus.queue import MessageBus
from simo.teacher_tools import TeacherEmailDraftTool, TeacherEmailSendTool


def _tool_context(bus: MessageBus | None = None) -> ToolContext:
    return ToolContext(config=SimpleNamespace(), workspace=".", bus=bus)


@pytest.mark.asyncio
async def test_email_draft_validates_recipient_and_never_sends() -> None:
    result = await TeacherEmailDraftTool(".").execute("class-7a", "student-003", "parent@example.com")
    assert result["status"] == "draft_only"
    assert result["to"] == "parent@example.com"
    assert "Support with Science" in result["subject"]


@pytest.mark.asyncio
async def test_email_send_requires_current_message_approval() -> None:
    bus = MessageBus()
    tool = TeacherEmailSendTool(_tool_context(bus))
    token = bind_request_context(RequestContext(
        channel="telegram",
        chat_id="teacher-1",
        original_user_text="Please send it",
    ))
    try:
        result = await tool.execute("parent@example.com", "Subject", "Body", "SEND EMAIL")
    finally:
        reset_request_context(token)
    assert result["status"] == "approval_required"


@pytest.mark.asyncio
async def test_email_send_queues_only_after_exact_approval() -> None:
    bus = MessageBus()
    tool = TeacherEmailSendTool(_tool_context(bus))
    token = bind_request_context(RequestContext(
        channel="telegram",
        chat_id="teacher-1",
        original_user_text="I reviewed it. SEND EMAIL",
    ))
    try:
        result = await tool.execute("parent@example.com", "Subject", "Body", "SEND EMAIL")
    finally:
        reset_request_context(token)
    assert result == {"status": "queued", "to": "parent@example.com", "subject": "Subject"}
