"""Deterministic rubric validation, level scoring, and teacher overrides."""

from __future__ import annotations

from dataclasses import dataclass

from simo.schemas import ReaderOutput, Rubric


class RubricScoringError(ValueError):
    """A proposed criterion or level is not part of the loaded rubric."""


@dataclass(frozen=True, slots=True)
class ScoredCriterion:
    criterion_id: str
    level_id: str
    points: int | float


def score_criterion(rubric: Rubric, criterion_id: str, level_id: str) -> ScoredCriterion:
    criterion = next((item for item in rubric.criteria if item.id == criterion_id), None)
    if criterion is None:
        raise RubricScoringError("unknown criterion id")
    level = next((item for item in criterion.levels if item.id == level_id), None)
    if level is None:
        raise RubricScoringError("unknown level id for criterion")
    return ScoredCriterion(criterion_id, level_id, level.points)


def score_total(scores: list[ScoredCriterion]) -> int | float:
    return sum(item.points for item in scores)


def score_teacher_override(
    rubric: Rubric,
    criterion_id: str,
    teacher_level_id: str,
) -> ScoredCriterion:
    """Recompute override points from the same rubric mapping as model grades."""
    return score_criterion(rubric, criterion_id, teacher_level_id)


def validate_reader_output(rubric: Rubric, output: ReaderOutput) -> None:
    expected = {criterion.id for criterion in rubric.criteria}
    received = {item.criterion_id for item in output.criteria}
    if expected != received:
        raise RubricScoringError("reader output criteria do not match rubric")
    for proposed in output.criteria:
        score_criterion(rubric, proposed.criterion_id, proposed.level_id)
