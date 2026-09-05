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
./venv/Scripts/python -m app.services.seed           # generates data, seeds DB, runs detection + evaluation

# 2. Start the API
./venv/Scripts/python -m uvicorn app.main:app --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev   # proxies /api to http://127.0.0.1:8000
```

Open the URL Vite prints (typically http://localhost:5173) — the dashboard
loads real detections from the seeded dataset immediately.

Re-run `python -m app.services.seed` any time to regenerate a fresh dataset
and re-run the full detect → diagnose → act → evaluate pipeline
(deterministic given the fixed seed).

### Tests

```bash
cd backend
./venv/Scripts/python -m pytest tests/ -q
```

32 tests covering detector correctness, money-at-risk arithmetic, root-cause
reconciliation, the bounded-action allowlist, the API surface, and the
evaluation pipeline. All pass against the seeded demo database (seed a
dataset first — `python -m app.services.seed` — same prerequisite the tests
document in `conftest.py`).

## What's actually here

- **Synthetic dataset**: ~11,400 payments (and related orders, refunds,
  settlements, settlement items, disputes, fees, bank transactions, ledger
  entries) across 45 merchants over 60 days, with 16 deliberately injected
  scenarios and a ground-truth label for every one of them (`data/synthetic/`,
  `data/ground_truth/`).
- **Detection engines** (`backend/app/analytics/detectors.py`): 11
  deterministic/statistical detectors — robust z-scores, EWMA-style trend
  detection, waterfall variance decomposition, and one lightweight
  isolation-style merchant-day anomaly score. No ML black box without
  retrievable evidence.
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
  `MockRazorpayProvider` (used throughout) and a structured
  `RazorpayTestModeProvider` stub for real Razorpay Test Mode credentials —
  not wired to network calls, not required to run the product.

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
  services/      data_generator, seed, pipeline, evaluation, overview
  analytics/     detectors.py, stats.py
  agents/        root_cause.py, action_engine.py, llm.py
  rules/         thresholds.py (documented, auditable constants)
  repositories/  data_repo.py (DB -> pandas)
  providers/     razorpay_provider.py (mock + test-mode stub)
  api/           routes.py
  tests/         32 tests

frontend/src/
  pages/         Overview, MoneyAtRisk, Exceptions(+Detail), FinancialEvents,
                 AgentInvestigation, RecoveryActions, AuditTrail, ModelPerformance
  components/    Sidebar, TopBar, KpiCard, HealthGauge, ExceptionRow, Badges
  services/      api.ts, merchantContext.tsx

data/
  synthetic/     generated CSVs + meta.json
  ground_truth/  anomaly_labels.csv
  benchmarks/    results.json

docs/            architecture.md, demo.md, evaluation.md
claude.md        repository history / institutional memory
context.md       current state snapshot for the next session
```

## Demo walkthrough

See `docs/demo.md` for the full 11-step walkthrough matching the product
brief (dashboard → click Money at Risk → evidence → root cause → recoverable
amount → safe auto action → escalation → audit trail → model performance).
