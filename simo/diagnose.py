"""Teacher decisions, mistake events, evidence-gated gap claims, and reports."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass

from simo.db import SimoDatabase, StoreError, _now
from simo.rubric import score_criterion
from simo.schemas import Rubric


@dataclass(frozen=True, slots=True)
class GapClaim:
    student_id: str
    concept_id: str
    status: str
    event_count: int
    item_count: int
    error_tags: tuple[str, ...]
    probe_required: bool


@dataclass(frozen=True, slots=True)
class Recommendation:
    concept_id: str
    kind: str
    reason: str
    evidence_count: int


def accept_proposed(
    database: SimoDatabase, teacher_id: str, class_id: str, submission_id: str,
    criterion_id: str, *, authenticated_teacher: bool,
) -> None:
    if not authenticated_teacher:
        raise StoreError("teacher authentication is required")
    with database._transaction() as conn:
        row = conn.execute(
            """SELECT j.status, j.flags, s.assessment_id, a.rubric_id
               FROM judgments j JOIN submissions s USING (teacher_id, class_id, submission_id)
               JOIN assessments a USING (teacher_id, class_id, assessment_id)
               WHERE j.teacher_id = ? AND j.class_id = ? AND j.submission_id = ? AND j.criterion_id = ?""",
            (teacher_id, class_id, submission_id, criterion_id),
        ).fetchone()
        if row is None:
            raise StoreError("judgment not found in the requested teacher/class scope")
        if row["status"] != "proposed" or json.loads(row["flags"]):
            raise StoreError("only unflagged proposed judgments can be accepted automatically")
        conn.execute(
            "UPDATE judgments SET status = 'accepted', updated_at = ? WHERE teacher_id = ? AND class_id = ? AND submission_id = ? AND criterion_id = ?",
            (_now(), teacher_id, class_id, submission_id, criterion_id),
        )
        _refresh_mistake_events(conn, teacher_id, class_id)


def override_judgment(
    database: SimoDatabase, teacher_id: str, class_id: str, submission_id: str,
    criterion_id: str, teacher_level_id: str, reason: str, *, authenticated_teacher: bool,
) -> None:
    if not authenticated_teacher:
        raise StoreError("teacher authentication is required")
    if not reason.strip():
        raise ValueError("override reason is required")
    with database._transaction() as conn:
        row = conn.execute(
            """SELECT s.assessment_id, a.rubric_id, r.json
               FROM submissions s JOIN assessments a USING (teacher_id, class_id, assessment_id)
               JOIN rubrics r USING (teacher_id, class_id, rubric_id)
               WHERE s.teacher_id = ? AND s.class_id = ? AND s.submission_id = ?""",
            (teacher_id, class_id, submission_id),
        ).fetchone()
        if row is None:
            raise StoreError("submission not found in the requested teacher/class scope")
        rubric = Rubric.model_validate_json(row["json"])
        score = score_criterion(rubric, criterion_id, teacher_level_id)
        cursor = conn.execute(
            """UPDATE judgments SET level_id = ?, points = ?, teacher_level_id = ?, teacher_reason = ?,
                 status = 'overridden', updated_at = ?
               WHERE teacher_id = ? AND class_id = ? AND submission_id = ? AND criterion_id = ?""",
            (score.level_id, score.points, score.level_id, reason.strip(), _now(),
             teacher_id, class_id, submission_id, criterion_id),
        )
        if cursor.rowcount != 1:
            raise StoreError("judgment not found in the requested teacher/class scope")
        _refresh_mistake_events(conn, teacher_id, class_id)


def diagnose_student(
    database: SimoDatabase, teacher_id: str, class_id: str, student_id: str, *,
    min_events: int = 2, min_items: int = 2,
) -> list[GapClaim]:
    if min_events < 1 or min_items < 1:
        raise ValueError("gap thresholds must be positive")
    with database._lock:
        rows = database._connection.execute(
            """SELECT e.concept_id, e.error_tag, e.assessment_id, s.question_id
               FROM mistake_events e JOIN judgments j ON j.judgment_id = e.evidence_ref
               JOIN submissions s ON s.teacher_id=j.teacher_id AND s.class_id=j.class_id
                 AND s.submission_id=j.submission_id
               WHERE e.teacher_id = ? AND e.class_id = ? AND e.student_id = ?""",
            (teacher_id, class_id, student_id),
        ).fetchall()
    # Events map to judgments, then submissions. Resolve distinct question IDs separately below.
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row["concept_id"]].append(row)
    claims: list[GapClaim] = []
    for concept_id, items in grouped.items():
        item_ids = {row["question_id"] or row["assessment_id"] for row in items}
        tags = tuple(sorted({row["error_tag"] for row in items if row["error_tag"]}))
        verified = len(items) >= min_events and len(item_ids) >= min_items
        claims.append(GapClaim(student_id, concept_id, "verified" if verified else "possible",
                               len(items), len(item_ids), tags, not verified))
    return sorted(claims, key=lambda claim: (-claim.event_count, claim.concept_id))


def recommend_next(
    rubric: Rubric, claims: list[GapClaim], *, prerequisite_event_counts: dict[str, int] | None = None,
) -> list[Recommendation]:
    """Rank concept gaps by count × rubric weight, probing a weak prerequisite first."""
    counts = prerequisite_event_counts or {}
    weights: Counter[str] = Counter()
    for criterion in rubric.criteria:
        weights[criterion.concept_id] += criterion.levels[-1].points
    ordered = sorted(claims, key=lambda c: (-(c.event_count * weights[c.concept_id]), c.concept_id))
    if not ordered:
        return []
    top = ordered[0]
    concept = next(item for item in rubric.concepts if item.id == top.concept_id)
    recommendations: list[Recommendation] = []
    for prerequisite in concept.prerequisites:
        prerequisite_evidence = counts.get(prerequisite, 0)
        if prerequisite_evidence < top.event_count:
            recommendations.append(Recommendation(
                prerequisite, "diagnostic_probe",
                "prerequisite evidence is weaker than the downstream gap", prerequisite_evidence,
            ))
    if not recommendations:
        recommendations.append(Recommendation(
            top.concept_id, "verified_gap" if top.status == "verified" else "possible_gap",
            "highest weighted gap based on teacher-reviewed work", top.event_count,
        ))
    return recommendations


def recommend_for_student(
    database: SimoDatabase, teacher_id: str, class_id: str, student_id: str, rubric: Rubric,
    *, min_events: int = 2, min_items: int = 2,
) -> list[Recommendation]:
    claims = diagnose_student(database, teacher_id, class_id, student_id,
                              min_events=min_events, min_items=min_items)
    with database._lock:
        rows = database._connection.execute(
            """SELECT s.question_id, j.criterion_id, r.json
               FROM judgments j JOIN submissions s USING (teacher_id, class_id, submission_id)
               JOIN assessments a USING (teacher_id, class_id, assessment_id)
               JOIN rubrics r USING (teacher_id, class_id, rubric_id)
               WHERE j.teacher_id = ? AND j.class_id = ? AND s.student_id = ?
                 AND j.status IN ('accepted', 'overridden') AND j.evidence_verified = 1
               """,
            (teacher_id, class_id, student_id),
        ).fetchall()
    evidence: dict[str, set[str]] = defaultdict(set)
    rubric_concepts: dict[str, dict[str, str]] = {}
    for row in rows:
        digest = row["json"]
        if digest not in rubric_concepts:
            parsed = Rubric.model_validate_json(digest)
            rubric_concepts[digest] = {criterion.id: criterion.concept_id for criterion in parsed.criteria}
        concept_id = rubric_concepts[digest].get(row["criterion_id"])
        if concept_id:
            evidence[concept_id].add(row["question_id"])
    evidence_counts = {concept_id: len(items) for concept_id, items in evidence.items()}
    return recommend_next(rubric, claims, prerequisite_event_counts=evidence_counts)


def class_report(database: SimoDatabase, teacher_id: str, class_id: str) -> dict:
    with database._lock:
        reviews = database._connection.execute(
            "SELECT count(*) FROM judgments WHERE teacher_id = ? AND class_id = ? AND status = 'needs_review'",
            (teacher_id, class_id),
        ).fetchone()[0]
        students = [row[0] for row in database._connection.execute(
            "SELECT student_id FROM roster WHERE teacher_id = ? AND class_id = ?",
            (teacher_id, class_id),
        ).fetchall()]
        rows = database._connection.execute(
            """SELECT concept_id, error_tag, count(*) AS events,
                      count(DISTINCT student_id) AS students
               FROM mistake_events WHERE teacher_id = ? AND class_id = ?
               GROUP BY concept_id, error_tag ORDER BY concept_id, error_tag""",
            (teacher_id, class_id),
        ).fetchall()
    shared_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    insufficient = 0
    for student in students:
        claims = diagnose_student(database, teacher_id, class_id, student)
        verified_claims = [claim for claim in claims if claim.status == "verified"]
        if not verified_claims:
            insufficient += 1
        for claim in verified_claims:
            shared_counts[claim.concept_id][0] += 1
            shared_counts[claim.concept_id][1] += claim.event_count
    shared = [
        {"concept_id": concept_id, "students": values[0], "events": values[1]}
        for concept_id, values in sorted(
            shared_counts.items(), key=lambda item: (-item[1][0], -item[1][1], item[0]),
        )
    ]
    return {
        "review_queue_size": int(reviews),
        "students_with_insufficient_evidence": int(insufficient),
        "mistakes_by_concept_and_error_tag": [dict(row) for row in rows],
        "top_shared_gaps": shared,
    }


def _refresh_mistake_events(conn, teacher_id: str, class_id: str) -> None:
    conn.execute("DELETE FROM mistake_events WHERE teacher_id = ? AND class_id = ?", (teacher_id, class_id))
    rows = conn.execute(
        """SELECT j.judgment_id, j.submission_id, j.criterion_id, j.level_id, j.teacher_level_id,
                  j.error_tag, j.status, s.student_id, s.assessment_id, a.rubric_id, r.json
           FROM judgments j JOIN submissions s USING (teacher_id, class_id, submission_id)
           JOIN assessments a USING (teacher_id, class_id, assessment_id)
           JOIN rubrics r USING (teacher_id, class_id, rubric_id)
           WHERE j.teacher_id = ? AND j.class_id = ? AND j.status IN ('accepted', 'overridden')""",
        (teacher_id, class_id),
    ).fetchall()
    now = _now()
    for row in rows:
        rubric = Rubric.model_validate_json(row["json"])
        criterion = next((item for item in rubric.criteria if item.id == row["criterion_id"]), None)
        if criterion is None:
            continue
        selected_level = row["teacher_level_id"] or row["level_id"]
        score = score_criterion(rubric, criterion.id, selected_level)
        if score.points >= criterion.levels[-1].points:
            continue
        conn.execute(
            """INSERT INTO mistake_events
               (teacher_id, class_id, student_id, concept_id, assessment_id, criterion_id,
                error_tag, evidence_ref, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (teacher_id, class_id, row["student_id"], criterion.concept_id, row["assessment_id"],
             criterion.id, row["error_tag"], row["judgment_id"], now),
        )
