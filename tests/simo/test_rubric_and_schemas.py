from __future__ import annotations

import pytest
from pydantic import ValidationError

from simo.rubric import (
    RubricScoringError,
    score_criterion,
    score_teacher_override,
    score_total,
    validate_reader_output,
)
from simo.schemas import ReaderOutput, Rubric


def rubric_data() -> dict:
    return {
        "rubric_id": "forces-1",
        "title": "Forces short answers",
        "concepts": [
            {"id": "force", "title": "Types of forces", "prerequisites": []},
            {"id": "newton", "title": "Newton's law", "prerequisites": ["force"]},
        ],
        "criteria": [
            {
                "id": "c1",
                "name": "States the law",
                "concept_id": "newton",
                "levels": [
                    {"id": "L0", "points": 0, "descriptor": "Incorrect or missing"},
                    {"id": "L1", "points": 1, "descriptor": "Partly correct"},
                    {"id": "L2", "points": 2, "descriptor": "Correct and complete"},
                ],
            }
        ],
    }


def test_rubric_rejects_duplicate_ids_unknown_concepts_and_non_increasing_points() -> None:
    data = rubric_data()
    data["concepts"].append(dict(data["concepts"][0]))
    with pytest.raises(ValidationError, match="concept ids must be unique"):
        Rubric.model_validate(data)

    data = rubric_data()
    data["criteria"][0]["concept_id"] = "missing"
    with pytest.raises(ValidationError, match="unknown concept"):
        Rubric.model_validate(data)

    data = rubric_data()
    data["criteria"][0]["levels"][2]["points"] = 1
    with pytest.raises(ValidationError, match="strictly increase"):
        Rubric.model_validate(data)

    data = rubric_data()
    data["criteria"].append(dict(data["criteria"][0]))
    with pytest.raises(ValidationError, match="criterion ids must be unique"):
        Rubric.model_validate(data)

    data = rubric_data()
    data["criteria"][0]["levels"][1]["id"] = "L0"
    with pytest.raises(ValidationError, match="level ids must be unique"):
        Rubric.model_validate(data)


def test_rubric_rejects_unknown_prerequisites_and_cycles() -> None:
    data = rubric_data()
    data["concepts"][0]["prerequisites"] = ["newton"]
    with pytest.raises(ValidationError, match="acyclic"):
        Rubric.model_validate(data)


def test_rubric_rejects_non_finite_and_negative_points() -> None:
    data = rubric_data()
    data["criteria"][0]["levels"][0]["points"] = -1
    with pytest.raises(ValidationError, match="non-negative"):
        Rubric.model_validate(data)

    data = rubric_data()
    data["criteria"][0]["levels"][1]["points"] = float("nan")
    with pytest.raises(ValidationError, match="finite"):
        Rubric.model_validate(data)

    data = rubric_data()
    data["total_points"] = 999
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Rubric.model_validate(data)

    data = rubric_data()
    data["concepts"][0]["prerequisites"] = ["not-here"]
    with pytest.raises(ValidationError, match="unknown prerequisite"):
        Rubric.model_validate(data)


def test_scoring_uses_level_mapping_and_teacher_override_recomputes_points() -> None:
    rubric = Rubric.model_validate(rubric_data())
    proposal = score_criterion(rubric, "c1", "L1")
    override = score_teacher_override(rubric, "c1", "L2")
    assert proposal.points == 1
    assert override.points == 2
    assert score_total([proposal, override]) == 3
    assert rubric.total_points == 2

    with pytest.raises(RubricScoringError, match="unknown level"):
        score_criterion(rubric, "c1", "L9")


def test_reader_schema_requires_level_ids_and_exact_criteria() -> None:
    rubric = Rubric.model_validate(rubric_data())
    with pytest.raises(ValidationError):
        ReaderOutput.model_validate({"criteria": [{"criterion_id": "c1", "level_id": 2}]})

    output = ReaderOutput.model_validate({
        "criteria": [{
            "criterion_id": "c1", "level_id": "L2", "evidence": ["F = ma"],
            "missing": None, "error_tag": None, "confidence": 0.9, "rationale": "Correct law.",
        }],
        "injection_suspected": False,
    })
    validate_reader_output(rubric, output)
    with pytest.raises(RubricScoringError, match="do not match"):
        validate_reader_output(rubric, ReaderOutput.model_validate({
            "criteria": [{
                "criterion_id": "other", "level_id": "L2", "confidence": 0.9, "rationale": "Okay.",
            }]
        }))
