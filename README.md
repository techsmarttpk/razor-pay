# Razorpay Financial Control Agent

**Track 04: AI Finance Controller** (with a concrete Track 03-style outcome: identifying and recovering money at risk)

> "Don't just tell the merchant that the books don't match. Tell them where money is at risk, why it is happening, what will happen next, and what can safely be done about it."

This is **not** a reconciliation product. It is a continuous financial control
layer that sits on top of Razorpay merchant operations: it detects
settlement/refund/fee anomalies, computes exactly how much money is at risk
with a transparent breakdown, diagnoses the root cause from actual evidence,
recommends a bounded action, executes the safe ones automatically, and logs
every decision to an append-only audit trail.

## Quick start

**Prerequisites:** Python 3.11+, Node 18+.

```bash
# 1. Backend — install deps and generate the demo dataset
cd backend
python -m venv venv
./venv/Scripts/pip install -r requirements.txt      # Windows
# source venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
./venv/Scripts/python -m app.services.seed           # generates data, seeds DB, trains the ML model,
                                                       # runs detection + evaluation

# 2. Start the API
./venv/Scripts/python -m uvicorn app.main:app --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev   # proxies /api to http://127.0.0.1:8000
```

Open the URL Vite prints (typically http://localhost:5173) — the dashboard
loads real detections from the seeded dataset immediately.

Re-run `python -m app.services.seed` any time to regenerate a fresh dataset,
retrain the ML anomaly model, and re-run the full
detect → diagnose → act → evaluate pipeline (deterministic given the fixed
seed — see "Machine learning" below). To retrain the model alone without
regenerating data: `./venv/Scripts/python -m app.services.train_ml_model`.

### Tests

```bash
cd backend
./venv/Scripts/python -m pytest tests/ -q
```

53 tests covering detector correctness, money-at-risk arithmetic, root-cause
reconciliation, the bounded-action allowlist, the API surface, the
evaluation pipeline, ML feature engineering, anti-leakage checks, and
Isolation Forest training/inference/thresholding. All pass against the
seeded demo database (seed a dataset first —
`python -m app.services.seed` — same prerequisite the tests document in
`conftest.py`).

## What's actually here

- **Synthetic dataset**: ~11,400 payments (and related orders, refunds,
  settlements, settlement items, disputes, fees, bank transactions, ledger
  entries) across 45 merchants over 60 days, with 16 deliberately injected
  scenarios and a ground-truth label for every one of them (`data/synthetic/`,
  `data/ground_truth/`).
- **Detection engines** (`backend/app/analytics/detectors.py`): 10
  deterministic/statistical detectors — robust z-scores, EWMA-style trend
  detection, waterfall variance decomposition — plus one detector
  (`merchant_level_anomaly`) that runs an OR-ensemble of the original
  hand-written heuristic and a genuinely trained `sklearn.ensemble.IsolationForest`
  (see "Machine learning" below). Every detector, ML included, returns the
  same evidence-bearing Finding shape — no black box without retrievable
  evidence.
- **Root-cause engine** (`backend/app/agents/root_cause.py`): for ambiguous
  settlement variance, walks refund timing → fee anomaly → chargeback
  reserve → delayed settlement → unknown, allocating the fixed variance
  across whichever hypotheses the evidence actually supports.
- **Money-at-risk engine**: every exception's amount is computed by plain
  arithmetic on the dataset, never guessed by an LLM, and the UI shows the
  exact component breakdown.
- **Bounded action engine** (`backend/app/agents/action_engine.py`): a hard
  allowlist of 8 action types, categorized SAFE_AUTO_ACTION / REVIEW_REQUIRED
  / ESCALATE by a deterministic function of confidence + amount + whether the
  root cause actually resolved. No real money moves.
- **Audit trail**: every agent decision writes an append-only `AuditEvent`
  row — visible end-to-end in the UI (WHY → EVIDENCE → CALCULATION →
  ROOT CAUSE → DECISION → ACTION → RESULT).
- **Evaluation** (`backend/app/services/evaluation.py`): scored only on the
  `holdout` split of ground truth (70/30 split at generation time,
  `calibration` is the only split thresholds were sanity-checked against) —
  see `/performance` in the UI or `data/benchmarks/results.json`.
- **LLM layer** (`backend/app/agents/llm.py`): explains/narrates
  already-computed facts; deterministic template by default, optionally
  backed by a real Claude call if `ANTHROPIC_API_KEY` is set. Never invents a
  number.
- **Razorpay provider abstraction** (`backend/app/providers/razorpay_provider.py`):
  `SyntheticRazorpayProvider` (used throughout) and a structured
  `RazorpayTestModeProvider` stub for real Razorpay Test Mode credentials —
  not wired to network calls, not required to run the product.

## Machine learning

There is exactly one trained ML model in this codebase, and it is scoped to
the one place a learned model is actually the right tool — see
`backend/app/ml/anomaly_model.py`'s module docstring for the full reasoning
and rejected alternatives (One-Class SVM, LOF, autoencoder, supervised
classification).

- **What**: `sklearn.ensemble.IsolationForest` over 13 engineered
  merchant-day features (`backend/app/analytics/features.py` — transaction
  volume/ticket size, refund rate/amount, fee excess, dispute rate,
  settlement delay, merchant-relative 30-day deviation z-scores, 7-day
  velocity, day-of-week seasonality — every feature documented with why it
  can indicate risk).
- **Where trained**: `backend/app/services/train_ml_model.py`
  (`python -m app.services.train_ml_model`, also run automatically by
  `seed`). Fits ONLY on the pre-injection period of the simulation window
  (the generator only ever injects merchant-level anomalies into the final
  10 days — see `data_generator.py`), so the model never sees the rows it
  is later scored/evaluated on.
- **Where loaded/inference happens**:
  `app/analytics/detectors.py::detect_merchant_level_anomalies_ml`, called
  from the same `run_all_detectors()` pipeline as every rule-based detector.
  Model artifact: `data/models/isolation_forest.joblib` +
  `isolation_forest_meta.json` (feature list, contamination assumption,
  seed, train/score row counts, calibration-selected threshold — nothing
  hardcoded).
- **Threshold**: selected by maximizing F1 on the `calibration`-split
  carrier merchants only; the `holdout`-split carriers are scored solely to
  report the final metrics in `data/benchmarks/ml_comparison.json` (also
  exposed at `/api/metrics` → `ml_comparison`, and rendered on the Model
  Performance page).
- **What it does NOT do**: it never computes a rupee amount by itself
  (money_at_risk still comes from a documented volume-share assumption,
  same as the heuristic it complements), never picks a root cause, and
  never decides or executes an action — it produces a Finding exactly like
  any other detector, which then goes through the same deterministic
  `root_cause.py` → `action_engine.py` → allowlist as everything else (see
  "Bounded action engine" above). ML cannot move money or bypass a review.
- **Honest result**: on this dataset's tiny merchant-level holdout
  population (6 positive / 12 negative merchants — small enough that these
  numbers are directional, not statistically conclusive), the safe
  rules-OR-ML ensemble recovers 2 of 6 holdout carriers the existing rules
  alone missed (`refund_rate_spike`, which the rules' own specialized
  detector for that scenario failed to catch in this run) at the cost of a
  higher false-positive rate — see the full comparison table on the Model
  Performance page or `data/benchmarks/ml_comparison.json`. This is
  reported as measured, not rounded up.

## Latest evaluation snapshot

Run `python -m app.services.seed` to regenerate; numbers below are from the
committed `data/benchmarks/results.json` (seed=42, held-out labels only):

| Metric | Value |
|---|---|
| Precision | 100% |
| Recall | 77% |
| F1 | 87% |
| False positive rate | 0% |
| Root cause accuracy | 96% |
| Auto-resolution precision | 100% |
| Money-at-risk estimation error (MAPE) | 0.3% |
| Throughput | ~4,600 records/sec |

These are real numbers off the held-out split, not hardcoded. Some scenario
types (fee_anomaly ~62%, settlement_variance ~46%) are intentionally harder
and recall is honestly below 100% there — see `/performance` in the app for
the full per-scenario breakdown.

## Project layout

```
backend/app/
  models/        SQLAlchemy ORM (financial entities + control-layer entities)
  services/      data_generator, seed, pipeline, evaluation, overview, train_ml_model
  analytics/     detectors.py, stats.py, features.py (ML feature engineering)
  ml/            anomaly_model.py (Isolation Forest: train/load/score/compare)
  agents/        root_cause.py, action_engine.py, llm.py
  rules/         thresholds.py (documented, auditable constants)
  repositories/  data_repo.py (DB -> pandas)
  providers/     razorpay_provider.py (synthetic + test-mode stub)
  api/           routes.py
  tests/         53 tests

frontend/src/
  pages/         Overview, MoneyAtRisk, Exceptions(+Detail), FinancialEvents,
                 AgentInvestigation, RecoveryActions, AuditTrail, ModelPerformance
  components/    Sidebar, TopBar, KpiCard, HealthGauge, ExceptionRow, Badges
  services/      api.ts, merchantContext.tsx

data/
  synthetic/     generated CSVs + meta.json
  ground_truth/  anomaly_labels.csv
  models/        isolation_forest.joblib + isolation_forest_meta.json (trained model artifact)
  benchmarks/    results.json, ml_comparison.json (rules vs ML vs ensemble)

docs/            architecture.md, demo.md, evaluation.md
claude.md        repository history / institutional memory
context.md       current state snapshot for the next session
```

## Demo walkthrough

See `docs/demo.md` for the full 11-step walkthrough matching the product
brief (dashboard → click Money at Risk → evidence → root cause → recoverable
amount → safe auto action → escalation → audit trail → model performance).
