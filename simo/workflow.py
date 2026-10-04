"""Persisted grading workflow with resumable, idempotent per-submission steps."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from simo.db import SimoDatabase, StoreError
from simo.rubric import RubricScoringError, validate_reader_output
from simo.schemas import ReaderOutput, Rubric
from simo.verify import VerifiedJudgment, persist_judgments, verify_reader_outputs


class Reader(Protocol):
    @property
    def tokens_used(self) -> int: ...

    def start_run(self, tokens_used: int) -> None: ...

    async def read(self, rubric: Rubric, submission_text: str) -> ReaderOutput: ...


@dataclass(frozen=True, slots=True)
class CriterionGradeSummary:
    criterion_id: str
    level_id: str
    points: int | float
    status: str
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubmissionGradeSummary:
    submission_id: str
    status: str
    criteria: tuple[CriterionGradeSummary, ...]


@dataclass(frozen=True, slots=True)
class GradeRunSummary:
    run_id: str
    status: str
    tokens_used: int
    submission: SubmissionGradeSummary
    error: str | None = None


class WorkflowEngine:
    """Coordinate reader, deterministic verification, and tenant-scoped storage."""

    def __init__(
        self,
        database: SimoDatabase,
        reader: Reader,
        *,
        confidence_threshold: float = 0.55,
        short_answer_chars: int = 20,
    ) -> None:
        self.database = database
        self.reader = reader
        self.confidence_threshold = confidence_threshold
        self.short_answer_chars = short_answer_chars

    async def grade_submission(
        self,
        teacher_id: str,
        class_id: str,
        assessment_id: str,
        submission_id: str,
        rubric: Rubric,
        *,
        run_id: str | None = None,
        grade_samples: int = 1,
    ) -> GradeRunSummary:
        if grade_samples < 1:
            raise ValueError("grade_samples must be at least 1")
        run_id = run_id or uuid.uuid4().hex
        if self.database.get_assessment_rubric(teacher_id, class_id, assessment_id) != rubric.rubric_id:
            raise StoreError("assessment rubric does not match the loaded rubric")
        submission = self.database.get_submission(teacher_id, class_id, submission_id)
        if submission.assessment_id != assessment_id:
            raise StoreError("submission does not belong to the requested assessment")
        self.database.create_run(teacher_id, class_id, run_id, assessment_id)
        self.reader.start_run(self.database.get_run_tokens(teacher_id, class_id, run_id))

        cached_read = self.database.get_run_step(teacher_id, class_id, run_id, submission_id, "read")
        outputs: list[ReaderOutput] | None = None
        if cached_read is not None and isinstance(cached_read.result, list):
            try:
                outputs = [
                    ReaderOutput.model_validate_json(json.dumps(item, ensure_ascii=False))
                    for item in cached_read.result
                ]
                for output in outputs:
                    validate_reader_output(rubric, output)
                outputs = outputs[:grade_samples]
            except (ValidationError, RubricScoringError, TypeError, KeyError):
                outputs = None
        if outputs is None:
            initial_outputs: list[ReaderOutput] = []
        else:
            initial_outputs = outputs
        if len(initial_outputs) < grade_samples:
            attempt = cached_read.attempt + 1 if cached_read else 1
            try:
                outputs = await self._read_and_store(
                    teacher_id, class_id, run_id, submission_id, rubric, submission.text_scrubbed,
                    grade_samples, attempt, initial_outputs,
                )
            except Exception as exc:
                tokens = self.reader.tokens_used
                self.database.finish_run(teacher_id, class_id, run_id, "partial", tokens)
                return GradeRunSummary(
                    run_id, "partial", tokens,
                    SubmissionGradeSummary(submission_id, "needs_review", ()),
                    "reader output unavailable or invalid; teacher review is required",
                )
        else:
            outputs = initial_outputs
            if cached_read is not None and cached_read.status != "completed":
                self.database.record_run_step(
                    teacher_id, class_id, run_id, submission_id, "read",
                    attempt=cached_read.attempt + 1, status="completed",
                    result=[item.model_dump(mode="json") for item in outputs],
                )

        cached_verify = self.database.get_run_step(teacher_id, class_id, run_id, submission_id, "verify")
        if cached_verify is not None and cached_verify.status == "completed" and isinstance(cached_verify.result, list):
            judgments = [_judgment_from_dict(item) for item in cached_verify.result]
        else:
            judgments = verify_reader_outputs(
                rubric,
                submission.text_scrubbed,
                outputs,
                confidence_threshold=self.confidence_threshold,
                short_answer_chars=self.short_answer_chars,
            )
            persist_judgments(self.database, teacher_id, class_id, submission_id, judgments)
            safe_result = [_judgment_to_dict(item, include_evidence=False) for item in judgments]
            prior_attempt = cached_verify.attempt + 1 if cached_verify else 1
            self.database.record_run_step(
                teacher_id, class_id, run_id, submission_id, "verify", attempt=prior_attempt,
                status="completed", result=safe_result,
            )

        status = "needs_review" if any(item.status == "needs_review" for item in judgments) else "proposed"
        tokens = self.reader.tokens_used
        self.database.finish_run(teacher_id, class_id, run_id, "completed", tokens)
        summary = SubmissionGradeSummary(
            submission_id,
            status,
            tuple(CriterionGradeSummary(
                item.criterion_id, item.level_id, item.points, item.status, item.flags
            ) for item in judgments),
        )
        return GradeRunSummary(run_id, "completed", tokens, summary)

    async def _read_and_store(
        self,
        teacher_id: str,
        class_id: str,
        run_id: str,
        submission_id: str,
        rubric: Rubric,
        submission_text: str,
        grade_samples: int,
        attempt: int,
        initial_outputs: list[ReaderOutput],
    ) -> list[ReaderOutput]:
        outputs = list(initial_outputs)
        self.database.record_run_step(
            teacher_id, class_id, run_id, submission_id, "read", attempt=attempt,
            status="running", result=[item.model_dump(mode="json") for item in outputs],
        )
        while len(outputs) < grade_samples:
            try:
                output = await self.reader.read(rubric, submission_text)
                validate_reader_output(rubric, output)
            except Exception as exc:
                self.database.record_run_step(
                    teacher_id, class_id, run_id, submission_id, "read", attempt=attempt,
                    status="needs_review", result=[item.model_dump(mode="json") for item in outputs],
                    error=type(exc).__name__,
                )
                self.database.update_run_tokens(
                    teacher_id, class_id, run_id, self.reader.tokens_used,
                )
                raise
            outputs.append(output)
            complete = len(outputs) == grade_samples
            self.database.record_run_step(
                teacher_id, class_id, run_id, submission_id, "read", attempt=attempt,
                status="completed" if complete else "running",
                result=[item.model_dump(mode="json") for item in outputs],
            )
            self.database.update_run_tokens(teacher_id, class_id, run_id, self.reader.tokens_used)
        return outputs


def _judgment_to_dict(judgment: VerifiedJudgment, *, include_evidence: bool) -> dict:
    result = {
        "criterion_id": judgment.criterion_id,
        "level_id": judgment.level_id,
        "points": judgment.points,
        "evidence_verified": judgment.evidence_verified,
        "error_tag": judgment.error_tag,
        "confidence": judgment.confidence,
        "samples_agree": judgment.samples_agree,
        "flags": list(judgment.flags),
        "status": judgment.status,
    }
    if include_evidence:
        result["verified_quotes"] = list(judgment.verified_quotes)
    return result


def _judgment_from_dict(value: dict) -> VerifiedJudgment:
    return VerifiedJudgment(
        criterion_id=str(value["criterion_id"]),
        level_id=str(value["level_id"]),
        points=value["points"],
        verified_quotes=tuple(value.get("verified_quotes", ())),
        evidence_verified=bool(value["evidence_verified"]),
        error_tag=value.get("error_tag"),
        confidence=float(value["confidence"]),
        samples_agree=value.get("samples_agree"),
        flags=tuple(value["flags"]),
        status=str(value["status"]),
    )
