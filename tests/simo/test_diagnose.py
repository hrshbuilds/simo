from __future__ import annotations

from pathlib import Path

import pytest

from simo.db import SimoDatabase, StoreError
from simo.diagnose import (
    accept_proposed, class_report, diagnose_student, override_judgment,
    recommend_for_student, recommend_next,
)
from simo.schemas import ErrorTag, ReaderOutput, Rubric
from simo.verify import persist_judgments, verify_reader_outputs


def make_rubric() -> Rubric:
    return Rubric.model_validate({
        "rubric_id": "physics-1",
        "title": "Physics",
        "concepts": [
            {"id": "forces", "title": "Forces"},
            {"id": "motion", "title": "Motion", "prerequisites": ["forces"]},
        ],
        "criteria": [
            {"id": "force-law", "name": "Force law", "concept_id": "forces", "levels": [
                {"id": "L0", "points": 0, "descriptor": "Incorrect"},
                {"id": "L1", "points": 1, "descriptor": "Partly correct"},
                {"id": "L2", "points": 2, "descriptor": "Correct"},
            ]},
            {"id": "motion-law", "name": "Motion law", "concept_id": "motion", "levels": [
                {"id": "L0", "points": 0, "descriptor": "Incorrect"},
                {"id": "L1", "points": 1, "descriptor": "Partly correct"},
                {"id": "L2", "points": 4, "descriptor": "Correct"},
            ]},
        ],
    })


def reader_output(motion_level: str) -> ReaderOutput:
    return ReaderOutput.model_validate({
        "criteria": [
            {"criterion_id": "force-law", "level_id": "L2", "evidence": ["force equals mass times acceleration"],
             "confidence": 0.9, "rationale": "Correct force law."},
            {"criterion_id": "motion-law", "level_id": motion_level,
             "evidence": ["force equals mass times acceleration"], "error_tag": ErrorTag.PREREQUISITE_GAP,
             "confidence": 0.9, "rationale": "Motion rule needs more detail."},
        ],
        "injection_suspected": False,
    })


def test_verified_gap_gate_prerequisite_probe_reports_and_teacher_override(tmp_path: Path) -> None:
    database = SimoDatabase(tmp_path / "simo.sqlite")
    try:
        database.create_teacher("teacher-1")
        database.create_class("teacher-1", "class-1", "Synthetic")
        database.create_class("teacher-1", "class-2", "Other")
        rubric = make_rubric()
        database.save_rubric("teacher-1", "class-1", rubric)
        database.create_assessment("teacher-1", "class-1", "quiz-1", rubric.rubric_id, "Synthetic quiz")
        database.add_student("teacher-1", "class-1", "student-1", "S-1", "Synthetic Student")
        database.add_student("teacher-1", "class-1", "student-2", "S-2", "Another Synthetic Student")

        for index, question in enumerate(("q1", "q2"), start=1):
            submission_id = f"submission-{index}"
            answer = "force equals mass times acceleration, because acceleration changes motion."
            database.add_submission(
                "teacher-1", "class-1", submission_id, "quiz-1", "student-1", question, answer,
            )
            judgments = verify_reader_outputs(rubric, answer, [reader_output("L1")])
            persist_judgments(database, "teacher-1", "class-1", submission_id, judgments)
            accept_proposed(database, "teacher-1", "class-1", submission_id, "motion-law",
                            authenticated_teacher=True)
            accept_proposed(database, "teacher-1", "class-1", submission_id, "force-law",
                            authenticated_teacher=True)

        claims = diagnose_student(database, "teacher-1", "class-1", "student-1")
        motion_gap = next(claim for claim in claims if claim.concept_id == "motion")
        assert (motion_gap.status, motion_gap.event_count, motion_gap.item_count) == ("verified", 2, 2)
        recommendation = recommend_next(rubric, claims)
        assert recommendation[0].concept_id == "forces"
        assert recommendation[0].kind == "diagnostic_probe"
        report = class_report(database, "teacher-1", "class-1")
        assert report["students_with_insufficient_evidence"] == 1
        assert report["mistakes_by_concept_and_error_tag"][0]["concept_id"] == "motion"
        assert recommend_for_student(database, "teacher-1", "class-1", "student-1", rubric)[0].concept_id == "motion"
        assert report["top_shared_gaps"][0]["students"] == 1

        with pytest.raises(StoreError, match="authentication"):
            override_judgment(database, "teacher-1", "class-1", "submission-1", "motion-law", "L2",
                              "Teacher correction", authenticated_teacher=False)
        override_judgment(database, "teacher-1", "class-1", "submission-1", "motion-law", "L2",
                          "Teacher correction", authenticated_teacher=True)
        row = database._connection.execute(
            "SELECT points, teacher_level_id, teacher_reason FROM judgments WHERE submission_id = 'submission-1' AND criterion_id = 'motion-law'"
        ).fetchone()
        assert (row["points"], row["teacher_level_id"], row["teacher_reason"]) == (4, "L2", "Teacher correction")
        assert len(diagnose_student(database, "teacher-1", "class-1", "student-1")) == 1
        assert diagnose_student(database, "teacher-1", "class-2", "student-1") == []
    finally:
        database.close()


def test_one_mistake_is_possible_gap_with_probe_required(tmp_path: Path) -> None:
    database = SimoDatabase(tmp_path / "simo.sqlite")
    try:
        database.create_teacher("teacher-1")
        database.create_class("teacher-1", "class-1", "Synthetic")
        rubric = make_rubric()
        database.save_rubric("teacher-1", "class-1", rubric)
        database.create_assessment("teacher-1", "class-1", "quiz-1", rubric.rubric_id, "Synthetic quiz")
        database.add_student("teacher-1", "class-1", "student-1", "S-1", "Synthetic Student")
        answer = "force equals mass times acceleration; details of changing motion are missing."
        database.add_submission("teacher-1", "class-1", "submission-1", "quiz-1", "student-1", "q1", answer)
        judgments = verify_reader_outputs(rubric, answer, [reader_output("L1")])
        persist_judgments(database, "teacher-1", "class-1", "submission-1", judgments)
        accept_proposed(database, "teacher-1", "class-1", "submission-1", "motion-law",
                        authenticated_teacher=True)
        claim = next(item for item in diagnose_student(database, "teacher-1", "class-1", "student-1")
                     if item.concept_id == "motion")
        assert (claim.status, claim.event_count, claim.probe_required) == ("possible", 1, True)
        assert recommend_next(rubric, [claim])[0].kind == "diagnostic_probe"
    finally:
        database.close()
