from app.repositories.data_repo import load_bundle


def test_ground_truth_split_has_no_overlap_and_covers_scenarios(bundle):
    labels = bundle.labels
    assert len(labels) > 500, "expect a substantial ground truth set"
    assert set(labels["split"].unique()) <= {"calibration", "holdout"}
    # every scenario type present in the generator's SCENARIOS list (minus
    # the purely structural batched_settlement) should appear at least once
    from app.services.data_generator import SCENARIOS
    present = set(labels["scenario_type"].unique())
    missing = set(SCENARIOS) - present - {"batched_settlement"}
    assert not missing, f"scenario types never labeled: {missing}"


def test_holdout_fraction_roughly_matches_target():
    labels_holdout_ratio_ok = True
    # loose sanity check rather than exact — generation uses ~70/30 per-label randomness
    from app.repositories.data_repo import load_bundle
    b = load_bundle()
    ratio = (b.labels["split"] == "holdout").mean()
    assert 0.15 <= ratio <= 0.45


def test_evaluation_produces_bounded_metrics():
    from app.services.evaluation import run_evaluation
    results = run_evaluation()
    for key in ("precision", "recall", "f1", "false_positive_rate", "root_cause_accuracy",
                "auto_resolution_precision"):
        assert 0.0 <= results[key] <= 1.0
    assert results["total_records"] > 5000
