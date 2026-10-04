"""Deterministic teacher workflow demo backed by synthetic data.

This module intentionally has no provider or nanobot dependency. It is the
smallest useful vertical slice for validating the teacher workflow locally
before connecting external services.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DemoStudent:
    id: str
    name: str
    marks: int
    missing_assignments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DemoClass:
    id: str
    name: str
    students: tuple[DemoStudent, ...]
    assignments: tuple[dict[str, Any], ...]


class TeacherDemoStore:
    """Read-only synthetic teacher data with explicit class selection."""

    def __init__(self, data_path: str | Path) -> None:
        path = Path(data_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.teacher = payload["teacher"]
        self._classes = {
            item["id"]: DemoClass(
                id=item["id"],
                name=item["name"],
                students=tuple(
                    DemoStudent(
                        id=student["id"],
                        name=student["name"],
                        marks=student["marks"],
                        missing_assignments=tuple(student["missing_assignments"]),
                    )
                    for student in item["students"]
                ),
                assignments=tuple(item["assignments"]),
            )
            for item in payload["classes"]
        }

    def _get_class(self, class_id: str) -> DemoClass:
        try:
            return self._classes[class_id]
        except KeyError as exc:
            raise ValueError(f"Unknown demo class: {class_id}") from exc

    def overview(self, class_id: str) -> dict[str, Any]:
        classroom = self._get_class(class_id)
        marks = [student.marks for student in classroom.students]
        return {
            "class_id": classroom.id,
            "class_name": classroom.name,
            "student_count": len(classroom.students),
            "average_marks": round(sum(marks) / len(marks), 1) if marks else 0,
            "students_needing_attention": [
                {"student_id": student.id, "student_name": student.name, "marks": student.marks}
                for student in classroom.students
                if student.marks < 60 or student.missing_assignments
            ],
            "assignments": list(classroom.assignments),
        }

    def missing_work(self, class_id: str) -> list[dict[str, Any]]:
        classroom = self._get_class(class_id)
        return [
            {
                "student_id": student.id,
                "student_name": student.name,
                "missing_assignments": list(student.missing_assignments),
            }
            for student in classroom.students
            if student.missing_assignments
        ]

    def weekly_report(self, class_id: str) -> dict[str, Any]:
        overview = self.overview(class_id)
        return {
            "teacher": self.teacher["name"],
            "subject": self.teacher["subject"],
            "class_name": overview["class_name"],
            "headline": (
                f"{overview['class_name']} has {overview['student_count']} students "
                f"with an average mark of {overview['average_marks']}."
            ),
            "wins": ["Most students completed the Forces quiz."],
            "focus_areas": [
                assignment["common_gap"]
                for assignment in overview["assignments"]
                if assignment["common_gap"]
            ],
            "follow_up": "Run a short mass-versus-weight example, then collect the lab reflection.",
        }

    def draft_message(self, class_id: str, student_id: str) -> dict[str, str]:
        classroom = self._get_class(class_id)
        student = next((item for item in classroom.students if item.id == student_id), None)
        if student is None:
            raise ValueError(f"Unknown demo student: {student_id}")
        missing = ", ".join(student.missing_assignments) or "no missing assignments"
        return {
            "student_id": student.id,
            "student_name": student.name,
            "status": "draft_only",
            "message": (
                f"Hi {student.name}, your current Science mark is {student.marks}. "
                f"Please review the next step: {missing}. "
                "Reply if you would like help before the next lesson."
            ),
            "approval_required": "true",
        }
