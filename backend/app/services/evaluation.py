"""Held-out evaluation of the detection + root-cause + action pipeline.

Ground truth (app/services/data_generator.py) is split at generation time
into `calibration` (thresholds in app/rules/thresholds.py were sanity-checked
against this split) and `holdout` (never used to pick a threshold — this is
the only split scored here). Numbers are computed straight from the
database; nothing here is hardcoded.
"""
import json
import os
import time

import pandas as pd
from sqlalchemy import text

from app.core.db import engine, DATA_DIR
from app.repositories.data_repo import load_bundle
from app.analytics.detectors import run_all_detectors


def _read(table):
    with engine.connect() as conn:
        return pd.read_sql(text(f"SELECT * FROM {table}"), conn)


def run_evaluation():
    labels = _read("anomaly_labels")
    exceptions = _read("exceptions")
    payments = _read("payments")

    holdout = labels[labels["split"] == "holdout"].copy()

    # index exceptions by entity_id -> list of (exception_type, root_cause_label, money_at_risk, status)
    exc_by_entity = {}
    for _, row in exceptions.iterrows():
        exc_by_entity.setdefault(row["entity_id"], []).append(row)

    tp, fp_rows, fn_rows = 0, [], []
    root_cause_correct, root_cause_total = 0, 0
    amount_errors = []
    auto_resolved_true, auto_resolved_total = 0, 0
    false_positive_holdout_negatives = 0
    true_negative_count = 0

    detected_entity_ids = set(exceptions["entity_id"].dropna().unique())

    for _, lbl in holdout.iterrows():
        matches = exc_by_entity.get(lbl["entity_id"], [])
        matched = [m for m in matches
                   if m["exception_type"] == lbl["scenario_type"]
                   or m["root_cause_label"] == lbl["scenario_type"]]

        if lbl["is_true_anomaly"]:
            if matched:
                tp += 1
                root_cause_total += 1
                if any(m["root_cause_label"] == lbl["scenario_type"] for m in matched):
                    root_cause_correct += 1
                if lbl["expected_amount"] and lbl["expected_amount"] > 0:
                    best = matched[0]
                    err = abs(best["money_at_risk"] - lbl["expected_amount"]) / lbl["expected_amount"]
                    amount_errors.append(err)
                for m in matched:
                    if m["status"] == "auto_resolved":
                        auto_resolved_total += 1
                        auto_resolved_true += 1
            else:
                fn_rows.append(lbl.to_dict())
        else:
            if matched:
                false_positive_holdout_negatives += 1
                fp_rows.append(lbl.to_dict())
                for m in matched:
                    if m["status"] == "auto_resolved":
                        auto_resolved_total += 1
            else:
                true_negative_count += 1

    n_positive = int((holdout["is_true_anomaly"] == True).sum())  # noqa: E712
    n_negative = int((holdout["is_true_anomaly"] == False).sum())  # noqa: E712
    fn = n_positive - tp
    fp = false_positive_holdout_negatives

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    fpr = fp / n_negative if n_negative else 0.0

    root_cause_accuracy = root_cause_correct / root_cause_total if root_cause_total else 0.0
    mape = sum(amount_errors) / len(amount_errors) if amount_errors else None
    auto_resolution_precision = auto_resolved_true / auto_resolved_total if auto_resolved_total else 0.0

    # throughput: fresh timed run of detectors over the full dataset
    t0 = time.time()
    bundle = load_bundle()
    _ = run_all_detectors(bundle)
    elapsed = time.time() - t0
    throughput = len(payments) / elapsed if elapsed > 0 else None

    total_money_at_risk = float(exceptions.loc[exceptions["status"].isin(
        ["open", "review_required", "escalated"]), "money_at_risk"].sum())
    total_resolved = float(exceptions.loc[exceptions["status"] == "auto_resolved", "money_at_risk"].sum())
    total_recoverable = float(exceptions["recoverable_amount"].sum())

    results = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "holdout_labels": int(len(holdout)),
        "calibration_labels": int((labels["split"] == "calibration").sum()),
        "total_records": int(len(payments)),
        "detected_entities": int(len(detected_entity_ids)),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": true_negative_count,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "root_cause_accuracy": round(root_cause_accuracy, 4),
        "root_cause_evaluated_on": root_cause_total,
        "money_at_risk_mape": round(mape, 4) if mape is not None else None,
        "money_at_risk_samples": len(amount_errors),
        "auto_resolution_precision": round(auto_resolution_precision, 4),
        "auto_resolution_evaluated_on": auto_resolved_total,
        "processing_throughput_records_per_sec": round(throughput, 1) if throughput else None,
        "total_exceptions": int(len(exceptions)),
        "auto_resolved_count": int((exceptions["status"] == "auto_resolved").sum()),
        "review_required_count": int((exceptions["status"] == "review_required").sum()),
        "escalated_count": int((exceptions["status"] == "escalated").sum()),
        "money_at_risk_open": round(total_money_at_risk, 2),
        "money_safely_resolved": round(total_resolved, 2),
        "total_recoverable_amount": round(total_recoverable, 2),
        "by_scenario": {},
    }

    for scenario, grp in holdout.groupby("scenario_type"):
        matched_count = 0
        for _, lbl in grp.iterrows():
            matches = exc_by_entity.get(lbl["entity_id"], [])
            if any(m["exception_type"] == lbl["scenario_type"] or m["root_cause_label"] == lbl["scenario_type"]
                   for m in matches):
                matched_count += 1
        results["by_scenario"][scenario] = {
            "holdout_count": int(len(grp)),
            "detected": matched_count,
            "is_true_anomaly": bool(grp["is_true_anomaly"].iloc[0]),
            "detection_rate": round(matched_count / len(grp), 3) if len(grp) else None,
        }

    out_dir = os.path.join(DATA_DIR, "benchmarks")
    os.makedirs(out_dir, exist_ok=True)

    # Fold in the ML-vs-rules comparison if app/services/train_ml_model.py
    # has been run (it is, as part of `seed`) — never hardcoded here, just
    # passed through from that file so /api/metrics exposes it in one place.
    ml_comparison_path = os.path.join(out_dir, "ml_comparison.json")
    if os.path.exists(ml_comparison_path):
        with open(ml_comparison_path) as f:
            results["ml_comparison"] = json.load(f)
    else:
        results["ml_comparison"] = None

    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    print(f"[eval] precision={precision:.2f} recall={recall:.2f} f1={f1:.2f} "
          f"fpr={fpr:.2f} root_cause_acc={root_cause_accuracy:.2f} "
          f"throughput={throughput:.0f} rec/s" if throughput else "[eval] done (no throughput)")
    return results


if __name__ == "__main__":
    run_evaluation()
