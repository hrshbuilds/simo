from __future__ import annotations

import asyncio
import json
from pathlib import Path

from simo.db import SimoDatabase
from simo.schemas import ReaderOutput, Rubric
from simo.workflow import WorkflowEngine


def _run(coro):
    try:
        coro.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("test coroutine unexpectedly suspended")


def rubric() -> Rubric:
    return Rubric.model_validate({
        "rubric_id": "forces-1",
        "title": "Forces",
        "concepts": [{"id": "force", "title": "Forces"}],
        "criteria": [{
            "id": "c1", "name": "States the law", "concept_id": "force",
            "levels": [
                {"id": "L0", "points": 0, "descriptor": "Incorrect"},
                {"id": "L1", "points": 1, "descriptor": "Partly correct"},
                {"id": "L2", "points": 2, "descriptor": "Correct and complete"},
            ],
        }],
    })


def output(level: str = "L2") -> ReaderOutput:
    return ReaderOutput.model_validate({
        "criteria": [{
            "criterion_id": "c1", "level_id": level,
            "evidence": ["force equals mass times acceleration"],
            "missing": None, "error_tag": None, "confidence": 0.9, "rationale": "Correct law.",
        }],
        "injection_suspected": False,
    })


class FakeReader:
    def __init__(self, outputs: list[ReaderOutput], *, fail_on_call: int | None = None) -> None:
        self.outputs = list(outputs)
        self.fail_on_call = fail_on_call
        self.calls = 0
        self.tokens_used = 0

    def start_run(self, tokens_used: int) -> None:
        self.tokens_used = tokens_used

    async def read(self, _rubric: Rubric, _submission_text: str) -> ReaderOutput:
        self.calls += 1
        self.tokens_used += 5
        if self.calls == self.fail_on_call:
            raise RuntimeError("synthetic transport failure")
        return self.outputs.pop(0)


def make_database(path: Path) -> tuple[SimoDatabase, Rubric]:
    database = SimoDatabase(path)
    current_rubric = rubric()
    database.create_teacher("teacher-1")
    database.create_class("teacher-1", "class-1", "Synthetic class")
    database.save_rubric("teacher-1", "class-1", current_rubric)
    database.create_assessment("teacher-1", "class-1", "assessment-1", "forces-1", "Synthetic quiz")
    database.add_student("teacher-1", "class-1", "student-1", "S-0001", "Synthetic Student")
    database.add_submission(
        "teacher-1", "class-1", "submission-1", "assessment-1", "student-1", "q1",
        "S-0001: force equals mass times acceleration",
    )
    return database, current_rubric


def test_workflow_keeps_answer_out_of_agent_summary_and_reuses_completed_steps(tmp_path: Path) -> None:
    database, current_rubric = make_database(tmp_path / "workflow.sqlite")
    reader = FakeReader([output(), output()])
    engine = WorkflowEngine(database, reader)
    try:
        first = _run(engine.grade_submission(
            "teacher-1", "class-1", "assessment-1", "submission-1", current_rubric,
            run_id="run-1", grade_samples=2,
        ))
        assert first.status == "completed"
        assert first.submission.status == "proposed"
        assert first.submission.criteria[0].points == 2
        assert "force equals mass" not in repr(first)
        assert "Synthetic Student" not in repr(first)
        assert reader.calls == 2

        read_step = database.get_run_step("teacher-1", "class-1", "run-1", "submission-1", "read")
        assert read_step is not None and read_step.status == "completed"
        assert isinstance(read_step.result, list) and len(read_step.result) == 2
        verify_step = database.get_run_step("teacher-1", "class-1", "run-1", "submission-1", "verify")
        assert verify_step is not None and verify_step.status == "completed"
        assert "verified_quotes" not in json.dumps(verify_step.result)

        again = _run(engine.grade_submission(
            "teacher-1", "class-1", "assessment-1", "submission-1", current_rubric,
            run_id="run-1", grade_samples=2,
        ))
        assert again == first
        assert reader.calls == 2
        assert database.get_run_tokens("teacher-1", "class-1", "run-1") == 10
    finally:
        database.close()


def test_workflow_resumes_from_saved_partial_reader_samples(tmp_path: Path) -> None:
    database, current_rubric = make_database(tmp_path / "resume.sqlite")
    first_reader = FakeReader([output()], fail_on_call=2)
    try:
        partial = _run(WorkflowEngine(database, first_reader).grade_submission(
            "teacher-1", "class-1", "assessment-1", "submission-1", current_rubric,
            run_id="run-resume", grade_samples=2,
        ))
        assert partial.status == "partial"
        assert first_reader.calls == 2
        partial_step = database.get_run_step(
            "teacher-1", "class-1", "run-resume", "submission-1", "read"
        )
        assert partial_step is not None and partial_step.status == "needs_review"
        assert isinstance(partial_step.result, list) and len(partial_step.result) == 1
        assert database.get_run_tokens("teacher-1", "class-1", "run-resume") == 10

        resume_reader = FakeReader([output()])
        resumed = _run(WorkflowEngine(database, resume_reader).grade_submission(
            "teacher-1", "class-1", "assessment-1", "submission-1", current_rubric,
            run_id="run-resume", grade_samples=2,
        ))
        assert resumed.status == "completed"
        assert resumed.tokens_used == 15
        assert resume_reader.calls == 1
    finally:
        database.close()
