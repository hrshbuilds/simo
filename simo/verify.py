"""Deterministic evidence verification and review routing."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from simo.db import SimoDatabase
from simo.rubric import score_criterion, validate_reader_output
from simo.schemas import ReaderOutput, Rubric


_INJECTION_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions\b",
    r"\b(?:system|developer|assistant)\s*:\s*",
    r"\byou are now\s+(?:the\s+)?(?:grader|teacher|assistant)\b",
    r"\b(?:give|award|assign)\s+(?:me\s+)?(?:full\s+)?(?:marks?|points?|score)\b",
    r"\b(?:score|mark)\s*[:=]\s*\d+",
))


@dataclass(frozen=True, slots=True)
class VerifiedJudgment:
    criterion_id: str
    level_id: str
    points: int | float
    verified_quotes: tuple[str, ...]
    evidence_verified: bool
    error_tag: str | None
    confidence: float
    samples_agree: bool | None
    flags: tuple[str, ...]
    status: str


def submission_has_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def verify_reader_outputs(
    rubric: Rubric,
    submission_text: str,
    outputs: list[ReaderOutput],
    *,
    confidence_threshold: float = 0.55,
    short_answer_chars: int = 20,
) -> list[VerifiedJudgment]:
    if not outputs:
        raise ValueError("at least one reader output is required")
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be between 0 and 1")
    for output in outputs:
        validate_reader_output(rubric, output)

    injected = submission_has_injection(submission_text) or any(
        output.injection_suspected for output in outputs
    )
    normalized_submission = _normalize(submission_text)
    judgments: list[VerifiedJudgment] = []
    for criterion in rubric.criteria:
        proposals = [next(item for item in output.criteria if item.criterion_id == criterion.id) for output in outputs]
        selected = proposals[0]
        score = score_criterion(rubric, criterion.id, selected.level_id)
        all_quotes = list(dict.fromkeys(quote for proposal in proposals for quote in proposal.evidence))
        verified_quotes = tuple(
            quote for quote in all_quotes
            if _normalize(quote) and _normalize(quote) in normalized_submission
        )
        all_evidence_verified = len(verified_quotes) == len(all_quotes)
        lowest_points = criterion.levels[0].points
        flags: set[str] = set()
        if not all_evidence_verified:
            flags.add("unverified_evidence")
        if score.points > lowest_points and not verified_quotes:
            flags.add("unverified_evidence")
        levels_agree = len({proposal.level_id for proposal in proposals}) == 1
        if not levels_agree:
            flags.add("disagreement")
        if injected:
            flags.add("injection_suspected")
        confidence = sum(proposal.confidence for proposal in proposals) / len(proposals)
        if confidence < confidence_threshold:
            flags.add("low_confidence")
        if (
            selected.level_id == criterion.levels[-1].id
            and len(normalized_submission) < short_answer_chars
        ):
            flags.add("short_answer_top_level")
        status = "needs_review" if flags else "proposed"
        judgments.append(VerifiedJudgment(
            criterion_id=criterion.id,
            level_id=selected.level_id,
            points=score.points,
            verified_quotes=verified_quotes,
            evidence_verified=all_evidence_verified and (
                score.points == lowest_points or bool(verified_quotes)
            ),
            error_tag=selected.error_tag.value if selected.error_tag else None,
            confidence=confidence,
            samples_agree=levels_agree if len(outputs) > 1 else None,
            flags=tuple(sorted(flags)),
            status=status,
        ))
    return judgments


def persist_judgments(
    database: SimoDatabase,
    teacher_id: str,
    class_id: str,
    submission_id: str,
    judgments: list[VerifiedJudgment],
) -> None:
    """Persist verified proposals; preserve any existing teacher override."""
    now = datetime.now(UTC).isoformat()
    with database._transaction() as conn:
        for judgment in judgments:
            if judgment.status not in {"proposed", "needs_review"}:
                raise ValueError("verified proposals cannot directly set a teacher decision")
            conn.execute(
                """INSERT INTO judgments
                   (teacher_id, class_id, submission_id, criterion_id, level_id, points,
                    evidence, evidence_verified, error_tag, confidence, samples_agree,
                    flags, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (teacher_id, class_id, submission_id, criterion_id)
                   DO UPDATE SET level_id=excluded.level_id, points=excluded.points,
                     evidence=excluded.evidence, evidence_verified=excluded.evidence_verified,
                     error_tag=excluded.error_tag, confidence=excluded.confidence,
                     samples_agree=excluded.samples_agree, flags=excluded.flags,
                     status=excluded.status, updated_at=excluded.updated_at
                   WHERE judgments.teacher_level_id IS NULL""",
                (teacher_id, class_id, submission_id, judgment.criterion_id, judgment.level_id,
                 judgment.points, json.dumps(judgment.verified_quotes, ensure_ascii=False),
                 int(judgment.evidence_verified), judgment.error_tag, judgment.confidence,
                 None if judgment.samples_agree is None else int(judgment.samples_agree),
                 json.dumps(judgment.flags), judgment.status, now),
            )


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())
