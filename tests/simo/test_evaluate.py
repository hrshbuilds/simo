from __future__ import annotations

import pytest

from eval.evaluate import evaluate, quadratic_weighted_kappa


def test_eval_metrics_measure_predictions_without_rendering_student_text() -> None:
    items = [
        {"id": "a", "gold_level_id": "L2", "gold_error_tag": None, "injection": True,
         "planted_review": True},
        {"id": "b", "gold_level_id": "L1", "gold_error_tag": "incomplete", "injection": False,
         "planted_review": False},
        {"id": "c", "gold_level_id": "L0", "gold_error_tag": "recall_failure", "injection": False,
         "planted_review": False},
    ]
    predictions = [
        {"id": "a", "level_id": "L2", "error_tag": None, "status": "needs_review",
         "flags": ["injection_suspected"], "injection_suspected": True,
         "evidence_quote_count": 1, "unverified_quote_count": 0, "tokens_used": 20},
        {"id": "b", "level_id": "L1", "error_tag": "incomplete", "status": "proposed",
         "flags": [], "evidence_quote_count": 1, "unverified_quote_count": 1, "tokens_used": 30},
        {"id": "c", "level_id": "L0", "error_tag": "recall_failure", "status": "needs_review",
         "flags": ["low_confidence"], "evidence_quote_count": 0, "unverified_quote_count": 0},
    ]
    metrics = evaluate(items, predictions, ["L0", "L1", "L2"])
    assert metrics["exact_level_agreement"] == 1
    assert metrics["quadratic_weighted_kappa"] == 1
    assert metrics["error_tag_accuracy"] == 1
    assert metrics["hallucinated_quote_rate"] == 0.5
    assert metrics["review_precision"] == 0.5
    assert metrics["review_recall"] == 1
    assert metrics["injection_unearned_level_rate"] == 0
    assert metrics["injection_flag_rate"] == 1
    assert metrics["mean_tokens"] == 25


def test_eval_rejects_incomplete_prediction_sets_and_kappa_handles_constant_labels() -> None:
    item = {"id": "a", "gold_level_id": "L0", "gold_error_tag": None,
            "injection": False, "planted_review": False}
    with pytest.raises(ValueError, match="exactly match"):
        evaluate([item], [], ["L0", "L1", "L2"])
    assert quadratic_weighted_kappa([0, 0], [0, 0], 3) == 1
    assert quadratic_weighted_kappa([0, 0], [1, 1], 3) == 0
