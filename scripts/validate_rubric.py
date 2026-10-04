"""Validate a Simo rubric JSON file using the runtime schema."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from simo.schemas import Rubric

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        rubric = Rubric.model_validate_json(args.path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        print(f"Invalid rubric: {exc}")
        return 1
    print(f"Valid rubric {rubric.rubric_id}: {len(rubric.criteria)} criteria, {rubric.total_points:g} maximum points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
