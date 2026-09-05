"""Trains the Isolation Forest merchant-anomaly model and writes the honest
model-comparison report. Run after `seed` (or as part of it):

    python -m app.services.train_ml_model

Writes:
    data/models/isolation_forest.joblib       - fitted model + scaler
    data/models/isolation_forest_meta.json    - training/threshold metadata
    data/benchmarks/ml_comparison.json        - existing rules vs statistical
                                                 heuristic vs Isolation Forest
                                                 vs ensemble, on held-out data
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core.db import DATA_DIR  # noqa: E402


def main():
    from app.repositories.data_repo import load_bundle
    from app.ml import anomaly_model as ml

    bundle = load_bundle()

    t0 = time.time()
    print("[train_ml_model] building features + fitting Isolation Forest ...")
    meta = ml.train_and_save(bundle)
    print(f"[train_ml_model] trained on {meta['train_rows']} merchant-day rows "
          f"({meta['train_merchants']} merchants) up to {meta['train_cutoff_day']}, "
          f"threshold={meta['threshold']:.4f} "
          f"(calibration F1={meta['calibration_metrics_at_threshold']['f1']}) "
          f"in {time.time()-t0:.2f}s")

    ml.clear_cache()
    print("[train_ml_model] running honest comparison against existing detectors ...")
    comparison = ml.run_comparison(bundle)
    for name, row in comparison["detectors"].items():
        print(f"[train_ml_model]   {name}: precision={row['precision']} recall={row['recall']} "
              f"f1={row['f1']} fpr={row['false_positive_rate']}")

    out_dir = os.path.join(DATA_DIR, "benchmarks")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ml_comparison.json")
    with open(out_path, "w") as f:
        json.dump(comparison, f, indent=2, default=str)
    print(f"[train_ml_model] wrote {out_path}")
    return meta, comparison


if __name__ == "__main__":
    main()
