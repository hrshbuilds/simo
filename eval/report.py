"""Print metrics for prediction files produced by live or replay runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", nargs="+", type=Path, help="JSON files with model and predictions fields")
    args = parser.parse_args()
    dataset = json.loads((Path(__file__).parent / "gold.json").read_text(encoding="utf-8"))
    rubric = json.loads((Path(__file__).parent / "rubric.json").read_text(encoding="utf-8"))
    level_ids = [level["id"] for level in rubric["criteria"][0]["levels"]]
    results = []
    for path in args.predictions:
        run = json.loads(path.read_text(encoding="utf-8"))
        results.append((run.get("model", path.stem), evaluate(dataset["items"], run["predictions"], level_ids)))
    metrics = list(results[0][1])
    widths = [max(32, len(metric))] + [max(20, len(name)) for name, _ in results]
    print(" | ".join(["metric".ljust(widths[0])] + [name.ljust(width) for (name, _), width in zip(results, widths[1:])]))
    print("-+-".join("-" * width for width in widths))
    for metric in metrics:
        cells = [metric.ljust(widths[0])]
        for (_, values), width in zip(results, widths[1:]):
            value = values[metric]
            rendered = "n/a" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)
            cells.append(rendered.ljust(width))
        print(" | ".join(cells))


if __name__ == "__main__":
    main()
