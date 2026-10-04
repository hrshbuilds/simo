from __future__ import annotations

from simo.teacher_demo import TeacherDemoStore


def test_demo_overview_is_deterministic_and_scoped() -> None:
    store = TeacherDemoStore("demo/teacher_data.json")
    overview = store.overview("class-7a")

    assert overview["class_name"] == "Class 7A"
    assert overview["student_count"] == 3
    assert overview["average_marks"] == 64.7
    assert [item["student_id"] for item in overview["students_needing_attention"]] == [
        "student-001",
        "student-003",
    ]


def test_demo_report_and_message_are_drafts() -> None:
    store = TeacherDemoStore("demo/teacher_data.json")

    report = store.weekly_report("class-7a")
    draft = store.draft_message("class-7a", "student-003")

    assert report["class_name"] == "Class 7A"
    assert "mass from weight" in " ".join(report["focus_areas"])
    assert draft["status"] == "draft_only"
    assert draft["approval_required"] == "true"


def test_unknown_demo_scope_fails_closed() -> None:
    store = TeacherDemoStore("demo/teacher_data.json")

    try:
        store.overview("class-unknown")
    except ValueError as exc:
        assert str(exc) == "Unknown demo class: class-unknown"
    else:
        raise AssertionError("unknown class should be rejected")
