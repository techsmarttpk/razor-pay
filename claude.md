# claude.md — repository history / institutional memory

This file is the persistent history of what was built and why. Update it
when architecture changes substantially; don't rewrite history that's still
accurate.

## What was built (2026-09-04, single autonomous session)

A full-stack MVP: **Razorpay Financial Control Agent** — a continuous
financial control layer over synthetic Razorpay merchant data, built for
Track 04 (AI Finance Controller) with a Track 03-style money-at-risk/recovery
outcome. Explicitly *not* a reconciliation product (see the mission brief
that started this session for the reasoning: Razorpay already ships
settlement reconciliation; the differentiator here is detect → diagnose →
quantify → prioritize → recommend → bounded-execute → audit, not "does this
transaction reconcile").

### Backend (Python 3.11, FastAPI, SQLAlchemy, SQLite, pandas, scikit-learn)

- `app/models/orm.py` — SQLAlchemy models. Financial entities (Merchant,
  Customer, Order, Payment, Refund, Settlement, SettlementItem, Dispute, Fee,
  BankTransaction, LedgerEntry) + control-layer entities (Exception_,
  Action, AuditEvent) + ground truth (AnomalyLabel). Note the trailing
  underscore on `Exception_` — `Exception` is a Python builtin.
- `app/services/data_generator.py` — synthetic dataset generator. Seed=42,
  45 merchants, 60 days, ~11,400 payments. Injects all 16 scenario types
  from the product brief and emits a ground-truth `AnomalyLabel` for each,
  split calibration/holdout (see docs/evaluation.md for the split
  methodology, including why merchant-level scenarios use a forced
  alternating split instead of a random draw).
- `app/services/seed.py` — the one command that resets the DB, generates
  data, loads it, exports CSVs to `data/synthetic/` and
  `data/ground_truth/`, and runs the full pipeline + evaluation.
  `python -m app.services.seed`.
- `app/analytics/detectors.py` — 11 detectors (fee anomaly + cohort rollup,
  delayed settlement, refund timing mismatch, duplicate transaction, missing
  settlement item, partial settlement, settlement variance, chargeback
  reserve, refund rate spike, settlement degradation, merchant-level
  anomaly). Each returns `Finding` dicts with money_at_risk, breakdown,
  evidence, confidence, severity — nothing hidden.
- `app/rules/thresholds.py` — every detector threshold as a documented plain
  constant, "calibrated" against the calibration split by inspection during
  development (not a learned model).
- `app/agents/root_cause.py` — the diagnostic tree. Unambiguous exception
  types confirm the detector's own classification. `settlement_variance`
  gets real diagnosis: waterfall-allocates the fixed variance across
  refund_timing → fee_anomaly → chargeback_reserve → delayed_settlement →
  unknown/unresolved, strongest evidence first, capped so components always
  sum exactly to the variance (see "known bugs fixed" below).
- `app/agents/action_engine.py` — hard 8-item action allowlist
  (`ALLOWED_ACTIONS`), `categorize()` deterministically assigns
  SAFE_AUTO_ACTION/REVIEW_REQUIRED/ESCALATE from confidence + amount +
  whether the classification actually resolved.
- `app/agents/llm.py` — `DeterministicTemplateProvider` (default, pure
  string templating over precomputed facts) + `AnthropicProvider` (used only
  if `ANTHROPIC_API_KEY` is set, falls back on any error). Never invents a
  number — the system prompt for the real-LLM path explicitly forbids it.
- `app/providers/razorpay_provider.py` — `MockRazorpayProvider` (used
  everywhere) + `RazorpayTestModeProvider` stub (structured but not wired to
  network calls; gated on `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`, which are
  not present in this environment and were never required).
- `app/services/pipeline.py` — orchestrates detect → diagnose → categorize →
  act → audit. Idempotent re-run (clears derived Exception/Action/AuditEvent
  rows, never touches raw financial data). Actions keyed by
  `{exception_id}:{action_type}` for idempotency.
- `app/services/evaluation.py` — scores only the `holdout` ground-truth
  split. Writes `data/benchmarks/results.json`. See docs/evaluation.md.
- `app/services/overview.py` — KPI aggregation for the dashboard (health
  scores, top exceptions).
- `app/api/routes.py` — all endpoints under `/api`: merchants, overview,
  exceptions (list/detail/action), actions, events, audit, metrics,
  pipeline/rerun, agent/ask.
- `tests/` — 32 tests (detectors, root cause reconciliation, action engine
  allowlist/categorization, API smoke tests, money-at-risk arithmetic,
  evaluation split integrity). All passing as of last run.

### Frontend (React 19 + TypeScript + Vite 8 + react-router-dom 7 + recharts 3)

Dark "financial control room" theme (`src/index.css` — CSS custom
properties, no Tailwind, no component library). 9 routes:
Overview, Money at Risk, Exceptions (+ detail drill-down), Financial Events,
Agent Investigation (chat, secondary), Recovery/Actions, Audit Trail, Model
Performance. `MerchantProvider` context drives a global merchant filter in
the top bar. `vite.config.ts` proxies `/api` to `127.0.0.1:8000` in dev.

The exception detail page (`ExceptionDetailPage.tsx`) implements the exact
WHY → EVIDENCE → CALCULATION → ROOT CAUSE → DECISION → ACTION → RESULT chain
from the product brief, with live action execution (RESOLVE SAFE ITEMS /
ESCALATE / create recovery case / group related exceptions) against
`POST /api/exceptions/{id}/actions/{action_type}`.

## ML upgrade (2026-09-05, second autonomous session)

A forensic pass (see `docs/razorpay-forensic-report.md`, dated 2026-09-05 —
left as-is, it's a point-in-time snapshot of the state *before* this
session's changes, not updated retroactively) found the real weakness in
the 2026-09-04 build: `sklearn.ensemble.IsolationForest` was imported but
never called (dead code in `stats.py`), and the detector named
`isolation_style_zscore` was actually a hand-rolled z-score sum that never
used it. Everything else in the pipeline (detectors, root cause, action
engine, audit trail, evaluation) was genuinely real, just not ML.

This session added exactly one trained ML model, scoped to exactly the one
place a learned model is the right tool — see
`backend/app/ml/anomaly_model.py`'s module docstring for the full
model-selection reasoning (why Isolation Forest, why not One-Class SVM/LOF/
autoencoder/supervised classification, and why the other 10 detectors stay
pure arithmetic/rules). Summary:

- **New**: `backend/app/analytics/features.py` (13 documented merchant-day
  features, no labels touched, `.shift(1)`-before-rolling so baselines never
  see their own day — see `tests/test_leakage.py`) and
  `backend/app/ml/anomaly_model.py` (train/load/score/threshold-select/
  compare). `backend/app/services/train_ml_model.py` is the CLI entry point,
  run automatically by `seed.py` right after the DB is loaded and before the
  detection pipeline runs (so `detect_merchant_level_anomalies_ml` has an
  artifact to load).
- **Changed**: `detect_merchant_level_anomalies` (in
  `app/analytics/detectors.py`) was split into
  `detect_merchant_level_anomalies_statistical` (the original heuristic,
  detector name corrected from the misleading `isolation_style_zscore` to
  `merchant_zscore_heuristic`), `detect_merchant_level_anomalies_ml` (real
  Isolation Forest inference), and `detect_merchant_level_anomalies_ensemble`
  (a safe OR-ensemble, keyed by merchant_id so money_at_risk is never
  double-counted when both signals agree — see that function's docstring).
  `ALL_DETECTORS` now registers the ensemble version. `stats.py`'s dead
  `isolation_forest_scores()` was deleted (superseded by the real thing in
  `app/ml/`), and `MockRazorpayProvider` was renamed
  `SyntheticRazorpayProvider` for honesty about what it is.
- **Measured, not assumed, that the ensemble is worth shipping**: trained
  the model, ran the identical holdout population through the existing
  rules, the old heuristic alone, the Isolation Forest alone, and the
  ensemble (`app/ml/anomaly_model.py::run_comparison`, written to
  `data/benchmarks/ml_comparison.json` and folded into `/api/metrics` via
  `evaluation.py`). On the committed run: existing rules combined
  recall 0.33/F1 0.36, the old heuristic alone recall 0.0/F1 0.0
  (it never caught its own namesake scenario on this holdout draw),
  Isolation Forest alone recall 0.5/F1 0.375, ensemble recall 0.67/F1 0.444.
  **The holdout population for this specific comparison is only 6 positive
  / 12 negative merchants** — small enough that these are directional
  results, not a statistically powered claim; reported as measured, per the
  mission brief's instruction not to fabricate or round up improvements.
  The concrete win: the Isolation Forest catches both holdout
  `refund_rate_spike` carriers that the rules (including that scenario's
  own dedicated `detect_refund_rate_spike` detector) miss on this draw — a
  real instance of the joint-signal argument in the model docstring, not
  just a theoretical one.
- **Frontend**: `ModelPerformancePage.tsx` renders a new "ML model:
  merchant-level anomaly detection" section (comparison table, model
  config, feature list) sourced entirely from `m.ml_comparison` in the
  `/api/metrics` response — nothing hardcoded. `types/index.ts` gained
  `MlComparison`/`MlDetectorResult`. `npm run build` passes clean.
  **Not independently browser-verified this session** — the
  `claude-in-chrome` extension was not connected in this environment
  (confirmed via `tabs_context_mcp`, not skipped); verification here is
  `tsc -b` type-checking + `curl localhost:8000/api/metrics` confirming the
  `ml_comparison` shape the page expects is actually present. A future
  session with browser access should do the visual walkthrough.
- **Tests**: added `test_features.py`, `test_leakage.py`, `test_ml_model.py`
  (21 new tests: feature shape/bounds, an explicit "truncate the dataset and
  confirm backward-looking features don't change" leakage check, source-code
  scans for forbidden label tokens, train/score split disjointness,
  calibration/holdout negative-pool disjointness, model persistence +
  reproducibility under the fixed seed, ensemble no-double-count, and a
  signature check that the action engine has no parameter for a raw ML
  score). 53/53 tests pass (`./venv/Scripts/python -m pytest tests/ -q`).
- **Not done / left as-is on purpose**: Razorpay Test Mode integration is
  still a stub (no credentials available or required — see Phase 12 of the
  brief that started this session); no Postgres run; frontend still one JS
  chunk. These were explicitly out of scope for "upgrade the detection
  engine," not overlooked.

## Known bugs found and fixed this session

1. **Root-cause waterfall double-counting** — `diagnose_settlement_variance`
   originally summed raw hypothesis amounts independently, which could
   exceed the total variance being explained (e.g. refund_timing raw signal
   ₹490 attributed against a ₹115 variance), breaking the invariant that
   `explained + residual == total_variance`. Caught by
   `tests/test_root_cause.py`. Fixed with a waterfall allocator
   (strongest-evidence-first, each hypothesis capped at remaining budget);
   raw signal strength preserved in `raw_amount` for evidence transparency.
2. **Duplicate transaction detector false-negative** — originally grouped by
   `(merchant_id, amount, method)` and required `order_ids[i] != order_ids[i-1]`,
   which is backwards: an accidental double-capture on the *same* order (the
   injected scenario) has the *same* order_id, so it was never flagged
   (0/17 holdout recall). Fixed by grouping on `order_id` directly.
3. **repeated_cohort_anomaly label/detector key mismatch** — the generator
   originally emitted one ground-truth label per day with
   entity_id=`merchant:method:day`, but the detector's cohort rollup key is
   `merchant:method` (no day) since the pattern spans many days. Zero
   overlap, zero recall. Fixed by emitting one label per merchant (not per
   day) with a matching key, computed post-hoc from actual generated data.
4. **refund_rate_spike z-score too strict for small merchants** — daily
   refund *count* rate is extremely noisy for small-tier merchants (1-5
   payments/day), so the baseline std was inflated and z-scores stayed low
   even at 5x ratio spikes. Relaxed z threshold (2.5→1.2), raised the ratio
   requirement to compensate (1.8x→2.5x), and added a minimum recent-volume
   gate so the rate is only trusted when it's based on enough payments.
5. **Dataset volume scaling bug** — the original per-merchant daily volume
   scaling formula (`avg_per_day / mid_of_tier_range`) collapsed all merchant
   tiers to the same ~3 payments/day regardless of size, undershooting the
   10,000-record target (6,505 actual) and defeating the small/medium/large
   tiering. Replaced with a single global scale factor computed from the
   expected raw total across all merchants, applied uniformly.

## Known limitations (intentional tradeoffs, not oversights)

- **No general cross-exception money-at-risk deduplication.** Each
  detector's money source is disjoint by construction (see
  docs/architecture.md, "Why detection engines never double-count money").
  This is correct for the current generator but wouldn't automatically hold
  if a new detector's money source could overlap an existing one — a future
  session adding detectors should check this.
- **Merchant-level scenarios (refund_rate_spike, merchant_level_anomaly,
  settlement_degradation) have low sample counts** (2-6 carrier merchants
  each) and correspondingly noisy holdout recall/precision — genuinely hard
  to detect reliably from so few instances, reported honestly rather than
  hidden or inflated. This is exactly why the ML comparison in
  `data/benchmarks/ml_comparison.json` is labeled directional, not
  statistically conclusive (see "ML upgrade" section above).
- **The Isolation Forest's contamination (0.03) is a documented estimate,
  not a fitted hyperparameter** — see `app/ml/anomaly_model.py` module
  docstring. A future session with a larger dataset could sweep this
  properly instead of estimating it from carrier-merchant counts.
- **RazorpayTestModeProvider is a structured stub, not a working
  integration** — no credentials were available or required; it documents
  exactly where real `razorpay-python` SDK calls would go.
- **No Postgres tested** — `DATABASE_URL` env var swap is wired
  (`app/core/db.py`) but only SQLite has actually been run.
- **Frontend has one large JS chunk** (~700KB, vite warns >500KB) — no
  code-splitting was done; acceptable for a demo, would matter for
  production.
- **The ML upgrade session (2026-09-05) could not visually verify the new
  frontend section in a browser** — `claude-in-chrome` was not connected in
  that environment. `tsc -b`/`vite build` passed and the API response shape
  was verified with `curl`, but nobody has looked at the rendered page.

## Commands

```bash
# Backend setup + seed (from backend/)
python -m venv venv
./venv/Scripts/pip install -r requirements.txt
./venv/Scripts/python -m app.services.seed        # regenerate data + train ML model + rerun pipeline + evaluation

# Retrain just the ML model (no data regeneration)
./venv/Scripts/python -m app.services.train_ml_model

# Run API
./venv/Scripts/python -m uvicorn app.main:app --port 8000

# Tests
./venv/Scripts/python -m pytest tests/ -q          # 53 tests, requires a seeded DB

# Frontend (from frontend/)
npm install
npm run dev                                        # proxies /api -> :8000
npm run build                                       # tsc -b && vite build (passes clean)
```

## What should NOT be changed casually

- **`app/rules/thresholds.py`** — these were tuned against real generated
  data to hit a defensible precision/recall balance (100% precision, 0%
  FPR, 77% recall on the committed run). Changing them without re-running
  `python -m app.services.seed` and checking `data/benchmarks/results.json`
  will silently change the honesty of the demo's headline numbers.
- **The waterfall allocation in `diagnose_settlement_variance`** — the
  ordering (refund → fee → chargeback → delayed) and the capping logic is
  what keeps `explained + residual == total_variance` true; see bug #1
  above and `tests/test_root_cause.py`.
- **Ground-truth label entity_id conventions** — must match exactly what
  each detector emits as `entity_id`/`exception_type` for `entity_id`-based
  matching in `evaluation.py` to work (see bugs #2, #3 above — this class of
  bug is easy to reintroduce when adding a new detector or scenario).
- **`ALLOWED_ACTIONS` in `action_engine.py`** — this is the safety boundary;
  never let `recommend_action()` or the API's execute-action endpoint bypass
  it (both currently `assert`/400 on anything outside the set). No ML
  score has, or should ever get, a path into this function that bypasses
  `Finding`/`diagnosis` (see `tests/test_ml_model.py::test_action_engine_never_sees_ml_score_directly`).
- **`app/ml/anomaly_model.py`'s time-based train/score split
  (`SCORE_WINDOW_DAYS = 10`)** — this is deliberately matched to the
  generator's own injection window (`data_generator.py`'s `is_last10`).
  Changing one without the other reintroduces the exact leakage this split
  exists to prevent (the model would be scored on days it was also fit on).
- **The ML threshold in `data/models/isolation_forest_meta.json`** — this
  is selected from calibration data, not hand-picked; don't hand-edit it.
  Regenerate via `python -m app.services.train_ml_model` (or `seed`) if the
  features, contamination, or dataset change.

## Next session should inspect first

1. `data/benchmarks/results.json` and `data/benchmarks/ml_comparison.json`
   — are they stale relative to the code? If thresholds, features, or the
   generator changed, re-run `python -m app.services.seed`.
2. `context.md` — the current-state snapshot, updated more frequently than
   this file.
3. Whether browser access is available this session — the ML upgrade
   session (2026-09-05) shipped a new frontend section
   (`ModelPerformancePage.tsx`) that passed `tsc -b`/`vite build` and an API
   shape check but was never visually verified in a running browser.
