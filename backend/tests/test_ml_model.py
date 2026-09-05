"""Isolation Forest training, persistence, inference, thresholding and
ensemble-detector behaviour (app/ml/anomaly_model.py + the
detect_merchant_level_anomalies_* functions in app/analytics/detectors.py)."""
import numpy as np
import pytest

from app.analytics.features import build_merchant_day_features, FEATURE_COLUMNS
from app.ml import anomaly_model as ml


@pytest.fixture(scope="module")
def trained(bundle):
    ml.clear_cache()
    meta = ml.train_and_save(bundle)
    ml.clear_cache()
    yield meta
    ml.clear_cache()


def test_training_produces_reasonable_metadata(trained):
    meta = trained
    assert meta["algorithm"] == "sklearn.ensemble.IsolationForest"
    assert meta["random_state"] == 42
    assert meta["feature_columns"] == FEATURE_COLUMNS
    assert meta["train_rows"] > 0
    assert meta["score_rows"] > 0
    assert isinstance(meta["threshold"], float)
    assert 0.0 <= meta["calibration_metrics_at_threshold"]["precision"] <= 1.0
    assert 0.0 <= meta["calibration_metrics_at_threshold"]["recall"] <= 1.0


def test_model_artifact_persists_and_reloads(bundle, trained):
    loaded = ml.load()
    assert loaded is not None
    model, scaler, meta = loaded
    features = build_merchant_day_features(bundle)
    _train_df, score_df, _cutoff = ml.time_split(features, meta["score_window_days"])
    scores = ml.score_dataframe(score_df, model, scaler)
    assert len(scores) == len(score_df)
    assert np.isfinite(scores).all()


def test_scoring_is_deterministic_given_fixed_seed(bundle, trained):
    """Retraining from scratch with the same seed on the same data must
    reproduce the same scores — a financial control system's ML component
    has to be reproducible, not a new answer every run."""
    features = build_merchant_day_features(bundle)
    _train_df, score_df, _cutoff = ml.time_split(features)

    model_a, scaler_a = ml.fit_isolation_forest(_train_df)
    scores_a = ml.score_dataframe(score_df, model_a, scaler_a)

    model_b, scaler_b = ml.fit_isolation_forest(_train_df)
    scores_b = ml.score_dataframe(score_df, model_b, scaler_b)

    assert np.allclose(scores_a, scores_b)


def test_confidence_mapping_is_bounded(trained):
    meta = trained
    for raw in (-1.0, meta["threshold"], 0.0, 1.0, 5.0):
        conf = ml.score_to_confidence(raw, meta)
        assert 0.0 <= conf <= 1.0


def test_ml_detector_returns_well_formed_findings(bundle, trained):
    from app.analytics.detectors import detect_merchant_level_anomalies_ml

    findings = detect_merchant_level_anomalies_ml(bundle)
    for f in findings:
        assert f["exception_type"] == "merchant_level_anomaly"
        assert f["detector"] == "isolation_forest"
        assert f["money_at_risk"] >= 0
        assert 0.0 <= f["confidence"] <= 1.0
        assert f["evidence"][0]["fields"]["peak_anomaly_score"] >= f["evidence"][0]["fields"]["threshold"]
        assert isinstance(f["evidence"][0]["fields"]["top_contributions"], list)


def test_ml_detector_returns_nothing_without_a_trained_model(bundle, monkeypatch, tmp_path):
    from app.analytics.detectors import detect_merchant_level_anomalies_ml

    ml.clear_cache()
    monkeypatch.setattr(ml, "MODEL_PATH", str(tmp_path / "nope.joblib"))
    monkeypatch.setattr(ml, "META_PATH", str(tmp_path / "nope.json"))
    try:
        findings = detect_merchant_level_anomalies_ml(bundle)
        assert findings == []
    finally:
        ml.clear_cache()


def test_ensemble_never_double_counts_a_merchant(bundle, trained):
    from app.analytics.detectors import detect_merchant_level_anomalies_ensemble

    findings = detect_merchant_level_anomalies_ensemble(bundle)
    merchant_ids = [f["merchant_id"] for f in findings]
    assert len(merchant_ids) == len(set(merchant_ids)), "ensemble must raise at most one finding per merchant"


def test_run_comparison_reports_bounded_metrics(bundle, trained):
    ml.clear_cache()
    results = ml.run_comparison(bundle)
    assert set(results["detectors"].keys()) == {
        "existing_rules_combined", "existing_statistical_heuristic",
        "isolation_forest", "ensemble_rules_or_ml",
    }
    for row in results["detectors"].values():
        for key in ("precision", "recall", "f1", "false_positive_rate"):
            assert 0.0 <= row[key] <= 1.0
        assert row["avg_inference_time_ms"] >= 0


def test_action_engine_never_sees_ml_score_directly(bundle, trained):
    """Safety boundary: the deterministic action engine only ever consumes
    the same Finding/diagnosis shape as every other detector — it has no
    parameter for a raw model score, so an ML detector cannot bypass
    categorize()/recommend_action()."""
    import inspect
    from app.agents import action_engine

    sig = inspect.signature(action_engine.categorize)
    assert list(sig.parameters) == ["finding", "diagnosis"]
    sig2 = inspect.signature(action_engine.recommend_action)
    assert list(sig2.parameters) == ["finding", "diagnosis"]
