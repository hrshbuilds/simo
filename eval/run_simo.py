"""Run the quarantined Simo reader over the synthetic gold set."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

async def run(output_path: Path) -> None:
    root = Path(__file__).parent
    sys.path.insert(0, str(root.parent))
    from simo.config import LLMConfig
    from simo.egress import EgressGuard
    from simo.llm import LLMClient
    from simo.reader import QuarantinedReader
    from simo.schemas import Rubric
    from simo.verify import verify_reader_outputs

    dataset = json.loads((root / "gold.json").read_text(encoding="utf-8"))
    rubric = Rubric.model_validate_json((root / "rubric.json").read_text(encoding="utf-8"))
    client = LLMClient(LLMConfig.from_env(), EgressGuard())
    reader = QuarantinedReader(client)
    predictions = []
    for item in dataset["items"]:
        reader.start_run(0)
        started = time.perf_counter()
        output = await reader.read(rubric, item["text"])
        judgment = verify_reader_outputs(rubric, item["text"], [output])[0]
        proposed = output.criteria[0]
        predictions.append({
            "id": item["id"],
            "level_id": judgment.level_id,
            "error_tag": judgment.error_tag,
            "status": judgment.status,
            "flags": list(judgment.flags),
            "injection_suspected": "injection_suspected" in judgment.flags,
            "evidence_quote_count": len(proposed.evidence),
            "unverified_quote_count": max(0, len(proposed.evidence) - len(judgment.verified_quotes)),
            "tokens_used": client.tokens_used,
            "latency_seconds": time.perf_counter() - started,
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"model": client.config.model, "predictions": predictions}, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("eval/predictions/simo.json"))
    args = parser.parse_args()
    asyncio.run(run(args.output))


if __name__ == "__main__":
    main()
