import pytest

from ux_swarm.evaluate import compute_metrics


def test_eval_recall_and_fp_from_labels():
    truth = {"issues": [{"id": "A1", "text": "x", "in_scope": True}, {"id": "A2", "text": "y", "in_scope": True},
                        {"id": "A3", "text": "z", "in_scope": False}],
             "stale": [{"id": "S1", "text": "fixed thing"}]}
    matches = {"A1": "I1", "A2": None, "A3": "I2", "S1": "I3"}
    rows = [
        {"issue_id": "I1", "prototype_gap": "False", "auto_label": "matches_truth", "auto_plausible": "", "human_label": ""},
        {"issue_id": "I2", "prototype_gap": "False", "auto_label": "matches_truth", "auto_plausible": "", "human_label": ""},
        {"issue_id": "I3", "prototype_gap": "False", "auto_label": "stale", "auto_plausible": "", "human_label": ""},
        {"issue_id": "I4", "prototype_gap": "False", "auto_label": "novel", "auto_plausible": "true", "human_label": "hallucinated"},
        {"issue_id": "I5", "prototype_gap": "False", "auto_label": "novel", "auto_plausible": "true", "human_label": ""},
        {"issue_id": "I6", "prototype_gap": "True", "auto_label": "novel", "auto_plausible": "false", "human_label": ""},
    ]
    m = compute_metrics(truth, matches, rows)
    assert m["recall"] == pytest.approx(0.5)  # A1 of {A1, A2}; A3 out of scope
    assert m["non_gap_issues"] == 5
    assert m["stale_rate"] == pytest.approx(1 / 5)
    assert m["false_positive_rate"] == pytest.approx(1 / 5)
    assert m["labels"]["real"] == 3
