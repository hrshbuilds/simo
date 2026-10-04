from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from simo.db import SimoDatabase, StoreError
from simo.schemas import Rubric


def sample_rubric() -> Rubric:
    return Rubric.model_validate({
        "rubric_id": "math-1",
        "title": "Arithmetic",
        "concepts": [{"id": "addition", "title": "Addition"}],
        "criteria": [{
            "id": "sum", "name": "Adds numbers", "concept_id": "addition",
            "levels": [
                {"id": "L0", "points": 0, "descriptor": "Incorrect"},
                {"id": "L1", "points": 1, "descriptor": "Correct"},
            ],
        }],
    })


def test_database_persists_rubric_and_scopes_queries_by_teacher_and_class(tmp_path: Path) -> None:
    database = SimoDatabase(tmp_path / "simo.sqlite")
    try:
        database.create_teacher("teacher-1")
        database.create_class("teacher-1", "class-a", "Morning")
        database.create_class("teacher-1", "class-b", "Afternoon")
        rubric = sample_rubric()
        digest = database.save_rubric("teacher-1", "class-a", rubric)
        assert len(digest) == 64
        assert database.get_rubric("teacher-1", "class-a", rubric.rubric_id) == rubric
        with pytest.raises(StoreError, match="scope"):
            database.get_rubric("teacher-1", "class-b", rubric.rubric_id)

        database.create_assessment("teacher-1", "class-a", "assessment-a", "math-1", "Quiz 1")
        database.add_student("teacher-1", "class-a", "student-a", "S-A001", "Synthetic Student")
        assert database.load_roster("teacher-1", "class-a")[0].real_name == "Synthetic Student"
        assert database.load_roster("teacher-1", "class-b") == []
        record = database.add_submission(
            "teacher-1", "class-a", "submission-a", "assessment-a", "student-a",
            "q1", "S-A001 answered 2 + 2 = 4",
        )
        assert len(record.text_sha256) == 64
        assert [item.submission_id for item in database.list_submissions(
            "teacher-1", "class-a", "assessment-a"
        )] == ["submission-a"]
        assert database.list_submissions("teacher-1", "class-b", "assessment-a") == []
        assert "Synthetic Student" not in repr(database.list_submissions(
            "teacher-1", "class-a", "assessment-a"
        ))
    finally:
        database.close()


def test_foreign_keys_reject_cross_scope_assessment_and_submission(tmp_path: Path) -> None:
    database = SimoDatabase(tmp_path / "simo.sqlite")
    try:
        database.create_teacher("teacher-1")
        database.create_class("teacher-1", "class-a", "Morning")
        database.create_class("teacher-1", "class-b", "Afternoon")
        database.save_rubric("teacher-1", "class-a", sample_rubric())
        with pytest.raises(sqlite3.IntegrityError):
            database.create_assessment("teacher-1", "class-b", "assessment-a", "math-1", "Quiz")
    finally:
        database.close()
