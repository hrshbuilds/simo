"""Strict typed data contracts for rubrics and quarantined reader output."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator


NonEmpty = Annotated[StrictStr, Field(min_length=1)]
Points = int | float


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Concept(StrictModel):
    id: NonEmpty
    title: NonEmpty
    prerequisites: list[NonEmpty] = Field(default_factory=list)


class Level(StrictModel):
    id: NonEmpty
    points: Points
    descriptor: NonEmpty


class Criterion(StrictModel):
    id: NonEmpty
    name: NonEmpty
    concept_id: NonEmpty
    levels: list[Level] = Field(min_length=2)


class Rubric(StrictModel):
    rubric_id: NonEmpty
    title: NonEmpty
    concepts: list[Concept] = Field(min_length=1)
    criteria: list[Criterion] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_structure(self) -> "Rubric":
        concept_ids = [concept.id for concept in self.concepts]
        criterion_ids = [criterion.id for criterion in self.criteria]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("concept ids must be unique")
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criterion ids must be unique")

        known_concepts = set(concept_ids)
        graph: dict[str, tuple[str, ...]] = {}
        for concept in self.concepts:
            prerequisites = concept.prerequisites
            if len(prerequisites) != len(set(prerequisites)):
                raise ValueError(f"duplicate prerequisite in concept {concept.id}")
            unknown = set(prerequisites) - known_concepts
            if unknown:
                raise ValueError(f"unknown prerequisite in concept {concept.id}")
            graph[concept.id] = tuple(prerequisites)
        if _has_cycle(graph):
            raise ValueError("concept prerequisite graph must be acyclic")

        for criterion in self.criteria:
            if criterion.concept_id not in known_concepts:
                raise ValueError(f"unknown concept for criterion {criterion.id}")
            level_ids = [level.id for level in criterion.levels]
            if len(level_ids) != len(set(level_ids)):
                raise ValueError(f"level ids must be unique within criterion {criterion.id}")
            points = [level.points for level in criterion.levels]
            if any(
                isinstance(point, bool)
                or (isinstance(point, float) and not math.isfinite(point))
                or point < 0
                for point in points
            ):
                raise ValueError(f"points must be finite and non-negative in criterion {criterion.id}")
            if any(right <= left for left, right in zip(points, points[1:])):
                raise ValueError(f"level points must strictly increase in criterion {criterion.id}")
        return self

    @property
    def total_points(self) -> int | float:
        """Compute the maximum from the highest level in each criterion."""
        return sum(criterion.levels[-1].points for criterion in self.criteria)


class ErrorTag(StrEnum):
    RECALL_FAILURE = "recall_failure"
    CONCEPT_CONFUSION = "concept_confusion"
    PREREQUISITE_GAP = "prerequisite_gap"
    CARELESS_ERROR = "careless_error"
    INCOMPLETE = "incomplete"


class ReaderCriterion(StrictModel):
    criterion_id: NonEmpty
    level_id: NonEmpty
    evidence: list[StrictStr] = Field(default_factory=list)
    missing: StrictStr | None = None
    error_tag: ErrorTag | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: StrictStr = Field(max_length=400)

    @model_validator(mode="after")
    def rationale_is_short(self) -> "ReaderCriterion":
        if len(self.rationale.split()) > 40:
            raise ValueError("rationale must be at most 40 words")
        return self


class ReaderOutput(StrictModel):
    criteria: list[ReaderCriterion] = Field(min_length=1)
    injection_suspected: StrictBool = False

    @model_validator(mode="after")
    def criterion_ids_are_unique(self) -> "ReaderOutput":
        ids = [item.criterion_id for item in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("reader output has duplicate criterion ids")
        return self


def _has_cycle(graph: dict[str, tuple[str, ...]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(prerequisite) for prerequisite in graph[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)
