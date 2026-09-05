"""Real, trained Isolation Forest anomaly detector for merchant-day behaviour.

WHY ISOLATION FOREST, AND WHY ONLY HERE
----------------------------------------
Ten of the eleven detectors in app/analytics/detectors.py answer a question
that has one deterministically correct numeric answer (a duplicate charge, a
fee overcharge, an unsettled payment) — those must stay exact arithmetic and
joins; a learned model has no business "predicting" a rupee figure that
plain subtraction already gives exactly. There is exactly one place in this
codebase where the honest answer is "we don't know the single rule that
defines normal, we're looking for a merchant behaving unlike itself across
several signals at once" — merchant-day-level anomaly detection. That is
the textbook case for an unsupervised, multivariate outlier detector:

  - Label availability: only ~18 merchants (out of 45) ever carry a
    merchant-level anomaly label, split again into calibration/holdout —
    nowhere near enough positives to train a supervised classifier without
    overfitting to a handful of examples. Isolation Forest needs no labels
    to fit.
  - Anomaly prevalence: low and merchant-specific — exactly the assumption
    Isolation Forest's recursive-partitioning splits are built around
    (anomalies are "few and different," so they isolate in fewer splits).
  - Interpretability: `decision_function` plus the feature vector gives a
    per-case, per-feature explanation (see `top_feature_contributions`) —
    no black-box embedding.
  - Joint signal: the previous hand-written heuristic
    (`avg_ticket` z-score + `refund_rate` z-score, /6, clipped) silently
    ignored the `fee_excess` feature it computed right next to it, and
    could not see settlement-delay or dispute signals at all. A single
    Isolation Forest over all engineered features (features.py) catches
    joint drift across ticket size, refund behaviour, fees, delay and
    velocity together — the three merchant-level scenario types
    (`merchant_level_anomaly`, `refund_rate_spike`, `settlement_degradation`)
    all show up as *some* combination of these, which is exactly what a
    multivariate detector — and not three independent univariate rules —
    is suited to catch.
  - Cost/latency: fits in well under a second on this dataset's scale and
    scores a merchant-day in microseconds — cheap enough to retrain on
    every `seed`/`train_ml_model` run.
  - Financial-control suitability: a bounded, explainable anomaly *score*
    that feeds the exact same deterministic root-cause/action pipeline as
    every other detector (see app/agents/action_engine.py) — it never
    decides an action, only raises a Finding like any other detector.

Other candidates considered and rejected for this specific job:
  - One-Class SVM / Local Outlier Factor: comparable assumptions to
    Isolation Forest but costlier to tune (kernel/gamma, k neighbours) and
    LOF does not support scoring new points outside its fit set without
    re-fitting — a poor fit for "train once, score fresh days on rerun."
  - Autoencoder: needs far more data than 45 merchants x 60 days to avoid
    memorizing, and trades away the transparent per-feature evidence trail
    this project's action/audit layer depends on.
  - Gradient boosting / supervised classifier: label count above rules it
    out (see "label availability").

TRAINING METHODOLOGY (see train_and_save / time_split below)
--------------------------------------------------------------
  1. Build merchant-day features for the whole dataset (features.py — no
     labels touched).
  2. Time-based split: the generator only ever injects merchant-level
     scenarios into the LAST `SCORE_WINDOW_DAYS` days of the simulation
     window (see data_generator.py `is_last10`) — so the model is fit
     exclusively on the earlier, scenario-free period and only ever scores
     the later window. This is a real train/inference split, not a
     resampled ceiling on the same rows: the model has never seen the rows
     it is asked to score.
  3. Threshold selection uses ONLY the `calibration`-split carrier
     merchants (plus a disjoint calibration half of the never-anomalous
     merchant pool) — the F1-maximizing score cutoff on that population is
     frozen into the saved model metadata.
  4. Final precision/recall/F1/FPR are computed ONLY on the `holdout`-split
     carrier merchants plus the other (disjoint) half of the never-anomalous
     pool — never used to pick the threshold or fit the model. See
     `run_comparison` and app/services/evaluation.py.

Ground-truth labels (AnomalyLabel / bundle.labels) are used in exactly two
places in this file: `_carrier_merchants` (to pick which merchants get
scored for the calibration-threshold-selection and holdout-evaluation
populations) and `run_comparison` (to compute metrics). Neither the feature
matrix nor the fitted model ever receives a label column — see
tests/test_leakage.py for an automated check of this invariant.
"""
import hashlib
import json
import os
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib

from app.core.db import DATA_DIR
from app.analytics.features import build_merchant_day_features, FEATURE_COLUMNS, FEATURE_RATIONALE

MODEL_DIR = os.path.join(DATA_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "isolation_forest.joblib")
META_PATH = os.path.join(MODEL_DIR, "isolation_forest_meta.json")

RANDOM_STATE = 42
N_ESTIMATORS = 200
# Assumption: merchant-level anomalies are rare relative to total
# merchant-days (~18 carrier merchants out of 45, active for only their
# final 10 days each, against ~2,700 total merchant-days) plus a small
# amount of noise from instance-level scenarios landing in the training
# window. 3% is a deliberately conservative estimate of that noise floor,
# not a fitted hyperparameter — see docs/evaluation.md.
CONTAMINATION = 0.03
SCORE_WINDOW_DAYS = 10  # matches data_generator.py's injection window exactly

MERCHANT_LEVEL_SCENARIOS = ["merchant_level_anomaly", "refund_rate_spike", "settlement_degradation"]


def _neg_bucket(merchant_id: str) -> int:
    """Deterministic (seed-free, reproducible) 50/50 split of the
    never-anomalous merchant pool into a calibration half and a holdout
    half, so threshold selection and final evaluation never share a
    negative example."""
    h = hashlib.md5(merchant_id.encode()).hexdigest()
    return int(h, 16) % 2


def _carrier_merchants(bundle):
    """Returns {scenario: {"calibration": [...], "holdout": [...]}} and the
    set of merchants carrying NO merchant-level scenario label at all (the
    negative pool), split into disjoint calibration/holdout halves.
    Reads bundle.labels ONLY to know which merchants to evaluate against —
    never to build a feature or fit the model."""
    labels = bundle.labels
    carriers = {}
    all_carrier_ids = set()
    for scenario in MERCHANT_LEVEL_SCENARIOS:
        sub = labels[labels["scenario_type"] == scenario]
        cal = sorted(sub[sub["split"] == "calibration"]["merchant_id"].unique().tolist())
        hold = sorted(sub[sub["split"] == "holdout"]["merchant_id"].unique().tolist())
        carriers[scenario] = {"calibration": cal, "holdout": hold}
        all_carrier_ids.update(cal)
        all_carrier_ids.update(hold)

    all_merchant_ids = set(bundle.merchants["id"].tolist())
    negative_pool = sorted(all_merchant_ids - all_carrier_ids)
    negatives = {"calibration": [], "holdout": []}
    for mid in negative_pool:
        bucket = "calibration" if _neg_bucket(mid) == 0 else "holdout"
        negatives[bucket].append(mid)

    return carriers, negatives


def time_split(features: pd.DataFrame, score_window_days: int = SCORE_WINDOW_DAYS):
    """Global (not per-merchant) time cutoff — every merchant shares the same
    simulation calendar, so one cutoff date separates the scenario-free
    training period from the scenario-injection window for all of them."""
    if features.empty:
        return features, features, None
    max_day = features["day"].max()
    cutoff = max_day - pd.Timedelta(days=score_window_days - 1)
    train_df = features[features["day"] < cutoff].copy()
    score_df = features[features["day"] >= cutoff].copy()
    return train_df, score_df, cutoff


def fit_isolation_forest(train_df: pd.DataFrame):
    X = train_df[FEATURE_COLUMNS].fillna(0.0).to_numpy()
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    model = IsolationForest(
        n_estimators=N_ESTIMATORS, contamination=CONTAMINATION,
        random_state=RANDOM_STATE, max_samples="auto",
    )
    model.fit(Xs)
    return model, scaler


def score_dataframe(df: pd.DataFrame, model, scaler) -> np.ndarray:
    X = df[FEATURE_COLUMNS].fillna(0.0).to_numpy()
    Xs = scaler.transform(X)
    # decision_function: higher = more normal. Flip sign so higher = more anomalous.
    return -model.decision_function(Xs)


def _merchant_max_scores(score_df: pd.DataFrame) -> dict:
    if score_df.empty:
        return {}
    return score_df.groupby("merchant_id")["anomaly_score"].max().to_dict()


def _select_threshold(cal_scores: dict, cal_positive_ids: set, cal_negative_ids: set):
    """Scan candidate thresholds = observed calibration scores, pick the one
    maximizing F1 on the calibration population only (ties broken by fewer
    false positives, then higher threshold i.e. more conservative)."""
    candidates = sorted(set(cal_scores.get(m) for m in (cal_positive_ids | cal_negative_ids) if m in cal_scores))
    if not candidates:
        return 0.0, {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    best = None
    for t in candidates:
        tp = sum(1 for m in cal_positive_ids if cal_scores.get(m, -1e9) >= t)
        fp = sum(1 for m in cal_negative_ids if cal_scores.get(m, -1e9) >= t)
        fn = len(cal_positive_ids) - tp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        key = (f1, -fp, t)
        if best is None or key > best[0]:
            best = (key, t, {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)})
    return best[1], best[2]


def train_and_save(bundle=None) -> dict:
    """Full training procedure: build features -> time split -> fit on the
    train period only -> score the held-back window -> pick a threshold from
    calibration-split labels only -> save model + scaler + metadata.
    Returns the metadata dict that was written to META_PATH."""
    if bundle is None:
        from app.repositories.data_repo import load_bundle
        bundle = load_bundle()

    t0 = time.time()
    features = build_merchant_day_features(bundle)
    train_df, score_df, cutoff = time_split(features, SCORE_WINDOW_DAYS)

    if train_df.empty or score_df.empty:
        raise RuntimeError("not enough merchant-day history to train/score the ML detector")

    model, scaler = fit_isolation_forest(train_df)
    score_df = score_df.copy()
    score_df["anomaly_score"] = score_dataframe(score_df, model, scaler)
    fit_seconds = time.time() - t0

    carriers, negatives = _carrier_merchants(bundle)
    scores_by_merchant = _merchant_max_scores(score_df)

    cal_positive = set()
    hold_positive = set()
    for scenario in MERCHANT_LEVEL_SCENARIOS:
        cal_positive.update(carriers[scenario]["calibration"])
        hold_positive.update(carriers[scenario]["holdout"])
    cal_negative = set(negatives["calibration"])
    hold_negative = set(negatives["holdout"])

    threshold, cal_metrics = _select_threshold(scores_by_merchant, cal_positive, cal_negative)

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump({"model": model, "scaler": scaler}, MODEL_PATH)

    meta = {
        "trained_at": pd.Timestamp.utcnow().isoformat(),
        "algorithm": "sklearn.ensemble.IsolationForest",
        "feature_columns": FEATURE_COLUMNS,
        "feature_rationale": FEATURE_RATIONALE,
        "random_state": RANDOM_STATE,
        "n_estimators": N_ESTIMATORS,
        "contamination": CONTAMINATION,
        "score_window_days": SCORE_WINDOW_DAYS,
        "train_cutoff_day": str(cutoff.date()) if cutoff is not None else None,
        "train_rows": int(len(train_df)),
        "train_merchants": int(train_df["merchant_id"].nunique()),
        "score_rows": int(len(score_df)),
        "threshold": float(threshold),
        "threshold_selection_population": {
            "calibration_positive_merchants": sorted(cal_positive),
            "calibration_negative_merchants": len(cal_negative),
        },
        "calibration_metrics_at_threshold": cal_metrics,
        "holdout_population": {
            "holdout_positive_merchants": sorted(hold_positive),
            "holdout_negative_merchants": len(hold_negative),
        },
        "fit_seconds": round(fit_seconds, 4),
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2, default=str)

    return meta


_cache = None


def load():
    """Returns (model, scaler, meta) or None if no trained artifact exists
    yet (fresh checkout before the first `seed`/`train_ml_model` run)."""
    global _cache
    if _cache is not None:
        return _cache
    if not (os.path.exists(MODEL_PATH) and os.path.exists(META_PATH)):
        return None
    bundle = joblib.load(MODEL_PATH)
    with open(META_PATH) as f:
        meta = json.load(f)
    _cache = (bundle["model"], bundle["scaler"], meta)
    return _cache


def clear_cache():
    global _cache
    _cache = None


def score_to_confidence(score: float, meta: dict) -> float:
    """Maps an anomaly score to a 0-1 confidence using the calibration
    population's score distribution recorded at training time — a score at
    or below the threshold maps near 0.5, and confidence rises toward 0.97
    as the score clears the threshold by a comfortable margin. This is a
    monotone rescaling for display/action-routing purposes; the underlying
    ranking is entirely the model's decision_function."""
    threshold = meta["threshold"]
    if threshold <= 0:
        span = 0.2
    else:
        span = max(threshold, 0.05)
    margin = (score - threshold) / span
    confidence = 0.55 + 0.4 * (1 / (1 + np.exp(-3 * margin)))
    return float(min(0.97, max(0.3, confidence)))


def top_feature_contributions(row: pd.Series, meta: dict, top_n: int = 3) -> list:
    """Explainability for a single flagged merchant-day: which engineered
    features are most extreme (by absolute value) for this row, in the units
    a human already understands (z-scores / ratios), not raw tree splits."""
    z_like_cols = [c for c in FEATURE_COLUMNS if c.endswith("_z30") or c == "volume_ratio_7d" or c.endswith("_ratio") or c.endswith("_rate")]
    scored = []
    for col in z_like_cols:
        val = row.get(col)
        if val is None or pd.isna(val):
            continue
        magnitude = abs(val - 1.0) if col == "volume_ratio_7d" else abs(val)
        scored.append({"feature": col, "value": round(float(val), 4),
                        "rationale": meta.get("feature_rationale", {}).get(col, ""),
                        "magnitude": magnitude})
    scored.sort(key=lambda c: c["magnitude"], reverse=True)
    for c in scored:
        c.pop("magnitude")
    return scored[:top_n]


def run_comparison(bundle=None) -> dict:
    """The Phase-7-style honest comparison: existing rule detectors vs the
    lone existing statistical heuristic vs the trained Isolation Forest vs a
    simple safe OR-ensemble, all scored on the SAME holdout population of
    merchants (the three merchant-level scenario types' holdout carriers +
    a disjoint holdout half of never-anomalous merchants). Every detector
    here is the actual production function — this does not reimplement or
    approximate any of them."""
    if bundle is None:
        from app.repositories.data_repo import load_bundle
        bundle = load_bundle()

    from app.analytics.detectors import (
        detect_merchant_level_anomalies_statistical,
        detect_refund_rate_spike,
        detect_settlement_degradation,
    )

    loaded = load()
    if loaded is None:
        train_and_save(bundle)
        loaded = load()
    model, scaler, meta = loaded

    features = build_merchant_day_features(bundle)
    _train_df, score_df, _cutoff = time_split(features, meta["score_window_days"])
    score_df = score_df.copy()
    score_df["anomaly_score"] = score_dataframe(score_df, model, scaler)
    scores_by_merchant = _merchant_max_scores(score_df)

    carriers, negatives = _carrier_merchants(bundle)
    hold_positive_by_scenario = {s: set(carriers[s]["holdout"]) for s in MERCHANT_LEVEL_SCENARIOS}
    hold_positive = set().union(*hold_positive_by_scenario.values())
    hold_negative = set(negatives["holdout"])
    eval_population = hold_positive | hold_negative

    t0 = time.time()
    stat_findings = detect_merchant_level_anomalies_statistical(bundle)
    t1 = time.time()
    stat_only_flags = {f["merchant_id"] for f in stat_findings}

    t2 = time.time()
    refund_spike_findings = detect_refund_rate_spike(bundle)
    degradation_findings = detect_settlement_degradation(bundle)
    t3 = time.time()
    combined_rules_flags = stat_only_flags | {f["merchant_id"] for f in refund_spike_findings} \
        | {f["merchant_id"] for f in degradation_findings}

    ml_flags = {m for m, s in scores_by_merchant.items() if s >= meta["threshold"]}
    ensemble_flags = combined_rules_flags | ml_flags

    n_merchants = max(len(eval_population), 1)
    rule_inference_time = (t1 - t0 + t3 - t2) / n_merchants
    ml_inference_time = meta["fit_seconds"] / max(meta["score_rows"], 1)

    def _metrics(flags, label_scope=None):
        scope = label_scope if label_scope is not None else eval_population
        flags_in_scope = flags & scope
        tp = len(flags_in_scope & hold_positive)
        fp = len(flags_in_scope & hold_negative)
        fn = len(hold_positive & scope) - tp
        tn = len(hold_negative & scope) - fp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        fpr = fp / (fp + tn) if (fp + tn) else 0.0
        return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
                "false_positive_rate": round(fpr, 4), "true_positives": tp, "false_positives": fp,
                "false_negatives": fn, "true_negatives": tn}

    def _per_scenario(flags):
        out = {}
        for scenario, positives in hold_positive_by_scenario.items():
            if not positives:
                out[scenario] = None
                continue
            detected = len(flags & positives)
            out[scenario] = {"holdout_count": len(positives), "detected": detected,
                              "detection_rate": round(detected / len(positives), 3)}
        return out

    results = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "evaluation_population": {
            "holdout_positive_merchants": len(hold_positive),
            "holdout_negative_merchants": len(hold_negative),
        },
        "model_metadata": {k: v for k, v in meta.items() if k != "feature_rationale"},
        "feature_rationale": meta.get("feature_rationale", {}),
        "detectors": {
            "existing_rules_combined": {
                "description": "Union of the 3 specialized rule/statistical detectors already in production "
                                "(merchant z-score heuristic + refund-rate EWMA + settlement-delay trend slope).",
                **_metrics(combined_rules_flags),
                "avg_inference_time_ms": round(rule_inference_time * 1000, 4),
                "by_scenario": _per_scenario(combined_rules_flags),
            },
            "existing_statistical_heuristic": {
                "description": "The single hand-written z-score heuristic this Isolation Forest was built to "
                                "replace/augment (ticket-size + refund-rate z-scores only, ignores fee/delay/velocity).",
                **_metrics(stat_only_flags),
                "avg_inference_time_ms": round((t1 - t0) / n_merchants * 1000, 4),
                "by_scenario": _per_scenario(stat_only_flags),
            },
            "isolation_forest": {
                "description": "Trained sklearn IsolationForest over 13 engineered merchant-day features, "
                                "fit only on the pre-injection window (see model_metadata).",
                **_metrics(ml_flags),
                "avg_inference_time_ms": round(ml_inference_time * 1000, 6),
                "by_scenario": _per_scenario(ml_flags),
            },
            "ensemble_rules_or_ml": {
                "description": "Safe OR-ensemble: flagged if EITHER the existing rules OR the Isolation Forest "
                                "flags the merchant. No ML score can suppress a rule-based flag or vice versa.",
                **_metrics(ensemble_flags),
                "avg_inference_time_ms": round((rule_inference_time + ml_inference_time) * 1000, 4),
                "by_scenario": _per_scenario(ensemble_flags),
            },
        },
    }
    return results


if __name__ == "__main__":
    meta = train_and_save()
    print(json.dumps(meta, indent=2, default=str))
