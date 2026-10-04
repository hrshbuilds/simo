"""Local SQLite storage with explicit teacher and class scoping."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from simo.identity import StudentIdentity
from simo.schemas import Rubric


_SCHEMA_VERSION = 2
_SCHEMA = """
CREATE TABLE teachers (
    teacher_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE classes (
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (teacher_id, class_id),
    FOREIGN KEY (teacher_id) REFERENCES teachers(teacher_id) ON DELETE CASCADE
);
CREATE TABLE roster (
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    student_id TEXT NOT NULL,
    pseudonym TEXT NOT NULL,
    real_name TEXT NOT NULL,
    name_variants TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (teacher_id, class_id, student_id),
    UNIQUE (teacher_id, class_id, pseudonym),
    FOREIGN KEY (teacher_id, class_id) REFERENCES classes(teacher_id, class_id) ON DELETE CASCADE
);
CREATE TABLE rubrics (
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    rubric_id TEXT NOT NULL,
    title TEXT NOT NULL,
    json TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (teacher_id, class_id, rubric_id),
    FOREIGN KEY (teacher_id, class_id) REFERENCES classes(teacher_id, class_id) ON DELETE CASCADE
);
CREATE TABLE concepts (
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    rubric_id TEXT NOT NULL,
    concept_id TEXT NOT NULL,
    title TEXT NOT NULL,
    prerequisites TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (teacher_id, class_id, rubric_id, concept_id),
    FOREIGN KEY (teacher_id, class_id, rubric_id)
      REFERENCES rubrics(teacher_id, class_id, rubric_id) ON DELETE CASCADE
);
CREATE TABLE assessments (
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    assessment_id TEXT NOT NULL,
    rubric_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (teacher_id, class_id, assessment_id),
    FOREIGN KEY (teacher_id, class_id, rubric_id)
      REFERENCES rubrics(teacher_id, class_id, rubric_id)
);
CREATE TABLE submissions (
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    assessment_id TEXT NOT NULL,
    student_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    text_scrubbed TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (teacher_id, class_id, submission_id),
    FOREIGN KEY (teacher_id, class_id, assessment_id)
      REFERENCES assessments(teacher_id, class_id, assessment_id),
    FOREIGN KEY (teacher_id, class_id, student_id)
      REFERENCES roster(teacher_id, class_id, student_id)
);
CREATE TABLE judgments (
    judgment_id INTEGER PRIMARY KEY,
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    level_id TEXT NOT NULL,
    points REAL NOT NULL,
    evidence TEXT NOT NULL,
    evidence_verified INTEGER NOT NULL,
    error_tag TEXT,
    confidence REAL,
    samples_agree INTEGER,
    flags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'proposed',
    teacher_level_id TEXT,
    teacher_reason TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (teacher_id, class_id, submission_id, criterion_id),
    FOREIGN KEY (teacher_id, class_id, submission_id)
      REFERENCES submissions(teacher_id, class_id, submission_id)
);
CREATE TABLE mistake_events (
    event_id INTEGER PRIMARY KEY,
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    student_id TEXT NOT NULL,
    concept_id TEXT NOT NULL,
    assessment_id TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    error_tag TEXT,
    evidence_ref INTEGER REFERENCES judgments(judgment_id),
    created_at TEXT NOT NULL,
    FOREIGN KEY (teacher_id, class_id, student_id)
      REFERENCES roster(teacher_id, class_id, student_id),
    FOREIGN KEY (teacher_id, class_id, assessment_id)
      REFERENCES assessments(teacher_id, class_id, assessment_id)
);
CREATE TABLE artifacts (
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (teacher_id, class_id, artifact_id),
    FOREIGN KEY (teacher_id, class_id) REFERENCES classes(teacher_id, class_id) ON DELETE CASCADE
);
CREATE TABLE approvals (
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    nonce TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (teacher_id, class_id, approval_id),
    FOREIGN KEY (teacher_id, class_id, artifact_id)
      REFERENCES artifacts(teacher_id, class_id, artifact_id)
);
CREATE TABLE runs (
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    assessment_id TEXT NOT NULL,
    status TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    PRIMARY KEY (teacher_id, class_id, run_id),
    FOREIGN KEY (teacher_id, class_id, assessment_id)
      REFERENCES assessments(teacher_id, class_id, assessment_id)
);
CREATE TABLE run_steps (
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    step TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    output_sha256 TEXT,
    result_json TEXT,
    error TEXT,
    PRIMARY KEY (teacher_id, class_id, run_id, item_id, step),
    FOREIGN KEY (teacher_id, class_id, run_id)
      REFERENCES runs(teacher_id, class_id, run_id) ON DELETE CASCADE
);
CREATE TABLE events (
    event_id INTEGER PRIMARY KEY,
    teacher_id TEXT NOT NULL,
    class_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (teacher_id, class_id) REFERENCES classes(teacher_id, class_id) ON DELETE CASCADE
);
"""


class StoreError(RuntimeError):
    """Storage operation failed or requested tenant-scoped data was missing."""


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    submission_id: str
    assessment_id: str
    student_id: str
    question_id: str
    text_scrubbed: str
    text_sha256: str
    created_at: str


@dataclass(frozen=True, slots=True)
class RunStepRecord:
    status: str
    attempt: int
    result: dict | list | str | int | float | bool | None
    error: str | None


class SimoDatabase:
    """A serialized local SQLite connection; every read requires its tenant keys."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 10000")
        if self.path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def create_teacher(self, teacher_id: str) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO teachers (teacher_id, created_at) VALUES (?, ?)",
                (_required(teacher_id, "teacher_id"), _now()),
            )

    def create_class(self, teacher_id: str, class_id: str, title: str) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO classes (teacher_id, class_id, title, created_at) VALUES (?, ?, ?, ?)",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(title, "title"), _now()),
            )

    def add_student(
        self,
        teacher_id: str,
        class_id: str,
        student_id: str,
        pseudonym: str,
        real_name: str,
        variants: tuple[str, ...] = (),
    ) -> None:
        with self._transaction() as conn:
            conn.execute(
                """INSERT INTO roster
                   (teacher_id, class_id, student_id, pseudonym, real_name, name_variants)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(student_id, "student_id"), _required(pseudonym, "pseudonym"),
                 _required(real_name, "real_name"), json.dumps(list(variants), ensure_ascii=False)),
            )

    def load_roster(self, teacher_id: str, class_id: str) -> list[StudentIdentity]:
        """Load names only inside the teacher/class identity boundary."""
        with self._lock:
            rows = self._connection.execute(
                """SELECT student_id, pseudonym, real_name, name_variants
                   FROM roster WHERE teacher_id = ? AND class_id = ? ORDER BY student_id""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id")),
            ).fetchall()
        return [
            StudentIdentity(
                row["student_id"], row["pseudonym"], row["real_name"],
                tuple(json.loads(row["name_variants"])),
            )
            for row in rows
        ]

    def save_artifact(self, teacher_id: str, class_id: str, artifact_id: str, kind: str, body: str) -> str:
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with self._transaction() as conn:
            conn.execute(
                """INSERT INTO artifacts (teacher_id, class_id, artifact_id, kind, body, sha256, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(artifact_id, "artifact_id"), _required(kind, "kind"), body, digest, _now()),
            )
        return digest

    def get_artifact(self, teacher_id: str, class_id: str, artifact_id: str) -> dict[str, str]:
        with self._lock:
            row = self._connection.execute(
                """SELECT artifact_id, kind, body, sha256 FROM artifacts
                   WHERE teacher_id = ? AND class_id = ? AND artifact_id = ?""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(artifact_id, "artifact_id")),
            ).fetchone()
        if row is None:
            raise StoreError("artifact not found in the requested teacher/class scope")
        return dict(row)

    def update_artifact(self, teacher_id: str, class_id: str, artifact_id: str, body: str) -> str:
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with self._transaction() as conn:
            cursor = conn.execute(
                """UPDATE artifacts SET body = ?, sha256 = ?
                   WHERE teacher_id = ? AND class_id = ? AND artifact_id = ?""",
                (body, digest, _required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(artifact_id, "artifact_id")),
            )
            if cursor.rowcount != 1:
                raise StoreError("artifact not found in the requested teacher/class scope")
        return digest

    def create_approval(
        self, teacher_id: str, class_id: str, approval_id: str, artifact_id: str,
        action: str, nonce: str, expires_at: str,
    ) -> str:
        with self._transaction() as conn:
            row = conn.execute(
                """SELECT sha256 FROM artifacts
                   WHERE teacher_id = ? AND class_id = ? AND artifact_id = ?""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(artifact_id, "artifact_id")),
            ).fetchone()
            if row is None:
                raise StoreError("artifact not found in the requested teacher/class scope")
            conn.execute(
                """INSERT INTO approvals
                   (teacher_id, class_id, approval_id, artifact_id, artifact_sha256, action,
                    nonce, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(approval_id, "approval_id"), _required(artifact_id, "artifact_id"),
                 row["sha256"], _required(action, "action"), _required(nonce, "nonce"),
                 _now(), _required(expires_at, "expires_at")),
            )
            return str(row["sha256"])

    def get_pending_approval(self, teacher_id: str, class_id: str, approval_id: str) -> dict[str, str] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT nonce, expires_at FROM approvals WHERE teacher_id = ? AND class_id = ?
                   AND approval_id = ? AND status = 'pending'""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(approval_id, "approval_id")),
            ).fetchone()
        return dict(row) if row is not None else None

    def resolve_approval(
        self, teacher_id: str, class_id: str, approval_id: str, nonce: str, status: str,
    ) -> bool:
        if status not in {"approved", "rejected"}:
            raise ValueError("approval status must be approved or rejected")
        with self._transaction() as conn:
            cursor = conn.execute(
                """UPDATE approvals SET status = ?, resolved_at = ?
                   WHERE teacher_id = ? AND class_id = ? AND approval_id = ? AND nonce = ?
                     AND status = 'pending' AND expires_at > ?""",
                (status, _now(), _required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(approval_id, "approval_id"), _required(nonce, "nonce"), _now()),
            )
            return cursor.rowcount == 1

    def has_valid_approval(self, teacher_id: str, class_id: str, artifact_id: str, action: str) -> bool:
        now = _now()
        with self._lock:
            row = self._connection.execute(
                """SELECT 1 FROM approvals a JOIN artifacts f
                   ON f.teacher_id = a.teacher_id AND f.class_id = a.class_id AND f.artifact_id = a.artifact_id
                   WHERE a.teacher_id = ? AND a.class_id = ? AND a.artifact_id = ? AND a.action = ?
                     AND a.status = 'approved' AND a.artifact_sha256 = f.sha256
                     AND a.expires_at > ? LIMIT 1""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(artifact_id, "artifact_id"), _required(action, "action"), now),
            ).fetchone()
        return row is not None

    def record_event(self, teacher_id: str, class_id: str, kind: str, payload: dict) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO events (teacher_id, class_id, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(kind, "kind"), json.dumps(payload, sort_keys=True), _now()),
            )

    def list_events(self, teacher_id: str, class_id: str, *, kind: str | None = None) -> list[dict]:
        query = "SELECT kind, payload, created_at FROM events WHERE teacher_id = ? AND class_id = ?"
        params: tuple = (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"))
        if kind is not None:
            query += " AND kind = ?"
            params += (_required(kind, "kind"),)
        query += " ORDER BY event_id"
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [{"kind": row["kind"], "payload": json.loads(row["payload"]), "created_at": row["created_at"]}
                for row in rows]

    def save_rubric(self, teacher_id: str, class_id: str, rubric: Rubric) -> str:
        payload = json.dumps(rubric.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        created_at = _now()
        with self._transaction() as conn:
            conn.execute(
                """INSERT INTO rubrics
                   (teacher_id, class_id, rubric_id, title, json, sha256, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 rubric.rubric_id, rubric.title, payload, digest, created_at),
            )
            conn.executemany(
                """INSERT INTO concepts
                   (teacher_id, class_id, rubric_id, concept_id, title, prerequisites)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (teacher_id, class_id, rubric.rubric_id, concept.id, concept.title,
                     json.dumps(concept.prerequisites, ensure_ascii=False))
                    for concept in rubric.concepts
                ],
            )
        return digest

    def get_rubric(self, teacher_id: str, class_id: str, rubric_id: str) -> Rubric:
        with self._lock:
            row = self._connection.execute(
                "SELECT json FROM rubrics WHERE teacher_id = ? AND class_id = ? AND rubric_id = ?",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(rubric_id, "rubric_id")),
            ).fetchone()
        if row is None:
            raise StoreError("rubric not found in the requested teacher/class scope")
        return Rubric.model_validate_json(row["json"])

    def create_assessment(
        self,
        teacher_id: str,
        class_id: str,
        assessment_id: str,
        rubric_id: str,
        title: str,
    ) -> None:
        with self._transaction() as conn:
            conn.execute(
                """INSERT INTO assessments
                   (teacher_id, class_id, assessment_id, rubric_id, title, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(assessment_id, "assessment_id"), _required(rubric_id, "rubric_id"),
                 _required(title, "title"), _now()),
            )

    def get_assessment_rubric(self, teacher_id: str, class_id: str, assessment_id: str) -> str:
        with self._lock:
            row = self._connection.execute(
                """SELECT rubric_id FROM assessments
                   WHERE teacher_id = ? AND class_id = ? AND assessment_id = ?""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(assessment_id, "assessment_id")),
            ).fetchone()
        if row is None:
            raise StoreError("assessment not found in the requested teacher/class scope")
        return str(row["rubric_id"])

    def add_submission(
        self,
        teacher_id: str,
        class_id: str,
        submission_id: str,
        assessment_id: str,
        student_id: str,
        question_id: str,
        text_scrubbed: str,
    ) -> SubmissionRecord:
        created_at = _now()
        digest = hashlib.sha256(text_scrubbed.encode("utf-8")).hexdigest()
        values = (
            _required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
            _required(submission_id, "submission_id"), _required(assessment_id, "assessment_id"),
            _required(student_id, "student_id"), _required(question_id, "question_id"),
            text_scrubbed, digest, created_at,
        )
        with self._transaction() as conn:
            conn.execute(
                """INSERT INTO submissions
                   (teacher_id, class_id, submission_id, assessment_id, student_id,
                    question_id, text_scrubbed, text_sha256, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
        return SubmissionRecord(submission_id, assessment_id, student_id, question_id, text_scrubbed, digest, created_at)

    def list_submissions(
        self,
        teacher_id: str,
        class_id: str,
        assessment_id: str,
    ) -> list[SubmissionRecord]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT submission_id, assessment_id, student_id, question_id, text_scrubbed,
                          text_sha256, created_at
                   FROM submissions
                   WHERE teacher_id = ? AND class_id = ? AND assessment_id = ?
                   ORDER BY created_at, submission_id""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(assessment_id, "assessment_id")),
            ).fetchall()
        return [SubmissionRecord(**dict(row)) for row in rows]

    def get_submission(
        self,
        teacher_id: str,
        class_id: str,
        submission_id: str,
    ) -> SubmissionRecord:
        with self._lock:
            row = self._connection.execute(
                """SELECT submission_id, assessment_id, student_id, question_id, text_scrubbed,
                          text_sha256, created_at
                   FROM submissions
                   WHERE teacher_id = ? AND class_id = ? AND submission_id = ?""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(submission_id, "submission_id")),
            ).fetchone()
        if row is None:
            raise StoreError("submission not found in the requested teacher/class scope")
        return SubmissionRecord(**dict(row))

    def create_run(
        self,
        teacher_id: str,
        class_id: str,
        run_id: str,
        assessment_id: str,
    ) -> None:
        tenant = (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"))
        with self._transaction() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO runs
                   (teacher_id, class_id, run_id, assessment_id, status, started_at)
                   VALUES (?, ?, ?, ?, 'running', ?)""",
                (*tenant, _required(run_id, "run_id"), _required(assessment_id, "assessment_id"), _now()),
            )
            row = conn.execute(
                "SELECT assessment_id FROM runs WHERE teacher_id = ? AND class_id = ? AND run_id = ?",
                (*tenant, run_id),
            ).fetchone()
            if row is None or row["assessment_id"] != assessment_id:
                raise StoreError("run id already belongs to a different assessment")

    def record_run_step(
        self,
        teacher_id: str,
        class_id: str,
        run_id: str,
        item_id: str,
        step: str,
        *,
        attempt: int,
        status: str,
        result: dict | list | str | int | float | bool | None = None,
        error: str | None = None,
    ) -> None:
        if attempt < 1:
            raise ValueError("attempt must be at least 1")
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if result is not None else None
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest() if encoded is not None else None
        with self._transaction() as conn:
            conn.execute(
                """INSERT INTO run_steps
                   (teacher_id, class_id, run_id, item_id, step, attempt, status,
                    output_sha256, result_json, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (teacher_id, class_id, run_id, item_id, step)
                   DO UPDATE SET attempt=excluded.attempt, status=excluded.status,
                     output_sha256=excluded.output_sha256, result_json=excluded.result_json,
                     error=excluded.error""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(run_id, "run_id"), _required(item_id, "item_id"), _required(step, "step"),
                 attempt, _required(status, "status"), digest, encoded, error),
            )

    def get_run_step(
        self,
        teacher_id: str,
        class_id: str,
        run_id: str,
        item_id: str,
        step: str,
    ) -> RunStepRecord | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT status, attempt, result_json, error FROM run_steps
                   WHERE teacher_id = ? AND class_id = ? AND run_id = ? AND item_id = ? AND step = ?""",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(run_id, "run_id"), _required(item_id, "item_id"), _required(step, "step")),
            ).fetchone()
        if row is None:
            return None
        result = json.loads(row["result_json"]) if row["result_json"] is not None else None
        return RunStepRecord(row["status"], row["attempt"], result, row["error"])

    def finish_run(self, teacher_id: str, class_id: str, run_id: str, status: str, tokens_used: int) -> None:
        if tokens_used < 0:
            raise ValueError("tokens_used cannot be negative")
        with self._transaction() as conn:
            cursor = conn.execute(
                """UPDATE runs SET status = ?, tokens_used = ?, finished_at = ?
                   WHERE teacher_id = ? AND class_id = ? AND run_id = ?""",
                (_required(status, "status"), tokens_used, _now(),
                 _required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(run_id, "run_id")),
            )
            if cursor.rowcount != 1:
                raise StoreError("run not found in the requested teacher/class scope")

    def get_run_tokens(self, teacher_id: str, class_id: str, run_id: str) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT tokens_used FROM runs WHERE teacher_id = ? AND class_id = ? AND run_id = ?",
                (_required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(run_id, "run_id")),
            ).fetchone()
        if row is None:
            raise StoreError("run not found in the requested teacher/class scope")
        return int(row["tokens_used"])

    def update_run_tokens(self, teacher_id: str, class_id: str, run_id: str, tokens_used: int) -> None:
        if tokens_used < 0:
            raise ValueError("tokens_used cannot be negative")
        with self._transaction() as conn:
            cursor = conn.execute(
                """UPDATE runs SET tokens_used = ?
                   WHERE teacher_id = ? AND class_id = ? AND run_id = ?""",
                (tokens_used, _required(teacher_id, "teacher_id"), _required(class_id, "class_id"),
                 _required(run_id, "run_id")),
            )
            if cursor.rowcount != 1:
                raise StoreError("run not found in the requested teacher/class scope")

    def _migrate(self) -> None:
        with self._lock:
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            if version == _SCHEMA_VERSION:
                return
            if version == 1:
                self._connection.executescript(
                    "BEGIN IMMEDIATE;\nALTER TABLE run_steps ADD COLUMN result_json TEXT;\n"
                    f"PRAGMA user_version = {_SCHEMA_VERSION};\nCOMMIT;"
                )
                return
            if version != 0:
                raise StoreError(f"unsupported database schema version: {version}")
            self._connection.executescript(
                f"BEGIN IMMEDIATE;\n{_SCHEMA}\nPRAGMA user_version = {_SCHEMA_VERSION};\nCOMMIT;"
            )

    def _transaction(self):
        return _Transaction(self._connection, self._lock)


class _Transaction:
    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock) -> None:
        self.connection = connection
        self.lock = lock

    def __enter__(self) -> sqlite3.Connection:
        self.lock.acquire()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
        except Exception:
            self.lock.release()
            raise
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            self.connection.rollback() if exc_type else self.connection.commit()
        finally:
            self.lock.release()


def _required(value: str, name: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{name} is required")
    return clean


def _now() -> str:
    return datetime.now(UTC).isoformat()
