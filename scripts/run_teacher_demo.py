"""Exercise the teacher-agent demo without Telegram or an LLM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simo.teacher_demo import TeacherDemoStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("demo/teacher_data.json"))
    parser.add_argument("--class-id", default="class-7a")
    parser.add_argument("--student-id", default="student-003")
    args = parser.parse_args()

    store = TeacherDemoStore(args.data)
    result = {
        "overview": store.overview(args.class_id),
        "missing_work": store.missing_work(args.class_id),
        "weekly_report": store.weekly_report(args.class_id),
        "message_draft": store.draft_message(args.class_id, args.student_id),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
