# context.md — current state snapshot

Last updated: 2026-09-05, end of the ML upgrade session (this repository IS
now a git repository — `git log` shows an initial commit predating this
session, so prefer `git log`/`git diff` over this file for exact recent
changes; this file stays useful as the current-state summary).

## Current product vision

Razorpay Financial Control Agent (Track 04 + Track 03 outcome). Full detail
in claude.md and docs/architecture.md. Not a reconciliation product —
detect/diagnose/quantify money at risk, recommend, bounded-execute, audit.
As of 2026-09-05, one of the eleven-ish detection surfaces
(`merchant_level_anomaly`) is a genuine ML model (Isolation Forest), not
just rules/statistics — see "ML upgrade" in claude.md and
`backend/app/ml/anomaly_model.py` for the full reasoning.

## Current repository state: MVP complete and verified working, ML upgrade applied

- Backend: FastAPI app, all endpoints implemented, 53 tests passing (32
  original + 21 new ML/feature/leakage tests).
- Frontend: React/Vite app, all 8 primary pages + chat, `npm run build`
  passes clean (no TS errors). Model Performance page now also renders a
  real ML-vs-rules comparison section — **not yet visually verified in a
  browser** (claude-in-chrome wasn't connected in the 2026-09-05 session;
  only type-checked + API-shape-checked).
- Dataset: seeded, 11,398 payments, 45 merchants, 963 ground-truth labels
  (unchanged by the ML upgrade — same generator, same seed=42).
- ML model: `data/models/isolation_forest.joblib` +
  `isolation_forest_meta.json`, trained on 2,250 pre-injection-window
  merchant-day rows, scored on 450 later rows, threshold selected from
  calibration data. Comparison in `data/benchmarks/ml_comparison.json`:
  ensemble recall 0.667/F1 0.444 vs existing-rules-only recall 0.333/F1
  0.364 on a 6-positive/12-negative holdout population — directional, not
  statistically powered (see docs/evaluation.md "ML model evaluation").
- Pipeline: runs end-to-end (detect → diagnose → act → audit → evaluate) in
  ~4 seconds; `seed.py` now also trains the ML model in between (+~0.5-1s).
- Evaluation: real numbers on held-out split — precision 1.00, recall 0.77,
  F1 0.87, FPR 0.00, root-cause accuracy 0.96, auto-resolution precision
  1.00, MAPE 0.35%, throughput ~4,300 records/sec. (Overall pipeline
  numbers essentially unchanged by the ML upgrade — it affects one detector
  among eleven-ish; see `data/benchmarks/ml_comparison.json` for the
  detector-specific comparison instead.)
- **Manually verified in-browser** (Chrome via claude-in-chrome tools):
  Overview, Exceptions list, Exception detail (full WHY→EVIDENCE→
  CALCULATION→ROOT CAUSE→DECISION→ACTION→RESULT chain, including a
  multi-hypothesis settlement_variance case), live action execution
  (ESCALATE button updated status + audit trail in real time), Money at
  Risk (chart + list), Recovery/Actions (table, after fixing a stale-backend
  404 — see below), Agent Investigation chat (deterministic answer, correct
  numbers). Model Performance page confirmed showing real, non-hardcoded
  metrics. **This browser walkthrough is from 2026-09-04, before the
  2026-09-05 ML upgrade added a new section to this exact page — that new
  section has only been type-checked/API-verified, not browser-verified.**

## What's completed (full acceptance checklist from the brief)

- [x] Backend starts successfully (`uvicorn app.main:app --port 8000`)
- [x] Frontend starts successfully (`npm run dev`, proxies to :8000)
- [x] Demo dataset loads (`python -m app.services.seed`)
- [x] Dashboard renders
- [x] Anomalies detected (483 exceptions from 11,398 payments)
- [x] Root causes correctly identified (96% accuracy on true positives)
- [x] Money-at-risk calculated (deterministic, breakdown shown, tests verify
      components sum exactly)
- [x] Evidence inspectable (evidence panel on every exception)
- [x] Safe action executes (SAFE_AUTO_ACTION, 239 auto-resolved in the seed run)
- [x] Uncertain action escalates (25 escalated in the seed run; manually
      triggered one live in-browser)
- [x] Audit trail visible (per-exception + global `/audit` page)
- [x] Evaluation metrics are real (computed in `evaluation.py`, not hardcoded)
- [x] Held-out evaluation runs (scores only the `holdout` label split)
- [x] Tests pass (32/32 as of 2026-09-04; 53/53 as of the 2026-09-05 ML upgrade)
- [x] README usable (setup, quick start, architecture summary, latest metrics)
- [x] claude.md exists and current
- [x] context.md exists and current (this file)

## Important files (see claude.md for full map)

- `backend/app/services/data_generator.py` — dataset + ground truth
- `backend/app/analytics/detectors.py` — detection engines (rules + the ML ensemble)
- `backend/app/analytics/features.py` — ML feature engineering (new, 2026-09-05)
- `backend/app/ml/anomaly_model.py` — Isolation Forest train/load/score/compare (new, 2026-09-05)
- `backend/app/services/train_ml_model.py` — ML training CLI entry point (new, 2026-09-05)
- `backend/app/agents/root_cause.py` — diagnostic tree (waterfall allocator)
- `backend/app/agents/action_engine.py` — bounded action allowlist + categorization
- `backend/app/services/pipeline.py` — orchestration
- `backend/app/services/evaluation.py` — held-out scoring (now also folds in ml_comparison.json)
- `backend/app/api/routes.py` — all API endpoints
- `frontend/src/pages/ExceptionDetailPage.tsx` — the core demo screen
- `frontend/src/pages/ModelPerformancePage.tsx` — now also renders the ML comparison (unverified in-browser)
- `frontend/src/index.css` — the entire design system

## Last successful commands (in order)

```
# 2026-09-04, initial build session
cd backend
python -m venv venv
./venv/Scripts/python.exe -m pip install -r requirements.txt
./venv/Scripts/python.exe -m app.services.seed          # multiple times, iterating on detector bugs
./venv/Scripts/python.exe -m pytest tests/ -q            # 32 passed
./venv/Scripts/python.exe -m uvicorn app.main:app --port 8000   # backend server (was left running)

cd ../frontend
npm create vite@latest . -- --template react-ts
npm install
npm install react-router-dom recharts axios
npm run build                                             # passes
npm run dev                                                # left running on :5174 (5173 was taken)

# 2026-09-05, ML upgrade session (from backend/)
./venv/Scripts/python -m app.services.seed               # regenerates data, trains ML model, reruns pipeline
./venv/Scripts/python -m pytest tests/ -q                 # 53 passed
cd ../frontend && npm run build                           # tsc -b && vite build, passes clean
```

## Current test status

53/53 backend tests passing (32 original + 21 new: `test_features.py`,
`test_leakage.py`, `test_ml_model.py`). No frontend unit tests were written
(deliberate tradeoff given the hackathon time constraint, not an oversight —
flagged here so a future session knows it's a gap, not a failure). The new
`ModelPerformancePage.tsx` ML section is type-checked (`tsc -b`) and
API-shape-verified (`curl` against a running backend) but not
browser-verified — `claude-in-chrome` was not connected in the 2026-09-05
session.

## Known bugs (all fixed — see claude.md "Known bugs found and fixed this
session" for full detail): root-cause waterfall double-counting, duplicate
detector grouping key, repeated_cohort_anomaly label/detector key mismatch,
refund_rate_spike z-score threshold, dataset volume scaling. All five were
caught either by the test suite or by inspecting `by_scenario` in the
evaluation output, then fixed and re-verified.

## Current known gaps / honest limitations

- `refund_rate_spike`, `merchant_level_anomaly` and `settlement_degradation`
  have small holdout sample counts (2 carrier merchants each) —
  correspondingly noisy precision/recall for both the rule detectors and
  the new Isolation Forest. See `data/benchmarks/ml_comparison.json` and
  claude.md's "ML upgrade" section for the honest, non-cherry-picked
  before/after comparison (ensemble recall 0.667 vs rules-only 0.333 on
  this tiny population — directional, not statistically conclusive).
- The Isolation Forest's `contamination=0.03` is a documented estimate, not
  swept/fitted — see `app/ml/anomaly_model.py` docstring.
- No Postgres run yet (SQLite only, though the abstraction is there).
- `RazorpayTestModeProvider` is an unwired stub (see claude.md) — still
  true after the ML upgrade; implementing it was explicitly out of scope
  (no credentials available or required).
- Frontend JS bundle is a single ~700KB chunk — no code splitting.
- This directory **is now a git repository** (an initial commit exists
  predating the 2026-09-05 ML upgrade session) — prefer `git log`/`git diff`
  over this file for exact recent changes.

## Immediate next actions (if resuming)

1. Confirm whether any backend/frontend dev servers are still running
   (`netstat -ano | findstr :8000` / `:5173` on Windows) or need
   restarting — see Quick Start in README.md.
2. If browser access is available, do the visual walkthrough of the new
   ML section on the Model Performance page (`/performance`) that the
   2026-09-05 session could not do — confirm the comparison table, model
   config tiles, and feature-rationale table render correctly against a
   freshly seeded backend.
3. If asked to make the demo "sharper," the highest-leverage next step is
   probably improving `refund_rate_spike`/`merchant_level_anomaly`/
   `settlement_degradation` recall (still the weakest scenario types even
   with the ML ensemble) or adding a couple more carrier merchants to
   shrink evaluation noise so the ML-vs-rules comparison is less noisy.

## Assumptions a future session must preserve

- **No real money movement, ever.** The action allowlist in
  `action_engine.py` is the safety boundary — do not add an action type that
  performs an irreversible financial operation. This applies identically to
  findings that originate from the ML detector — see
  `tests/test_ml_model.py::test_action_engine_never_sees_ml_score_directly`.
- **The LLM never computes a financial amount.** All amounts flow from
  deterministic code in `detectors.py`/`root_cause.py`; `llm.py` only
  phrases already-computed facts.
- **The ML model never computes a financial amount either, and never picks
  an action.** It only returns a `Finding` (same shape as every rule-based
  detector) that flows through the same `diagnose()` →
  `categorize()`/`recommend_action()` → allowlist pipeline. See
  "ML model boundary" in docs/architecture.md.
- **Evaluation must stay held-out.** Never let `run_evaluation()` score
  against the `calibration` split, and never hand-edit
  `data/benchmarks/results.json` or `data/benchmarks/ml_comparison.json`.
- **The ML model must stay reproducible.** `app/ml/anomaly_model.py` uses a
  fixed `random_state=42` and a time-based (not random) train/score split
  matched to the generator's injection window — don't introduce
  non-determinism (e.g. an unseeded random split) without updating
  `tests/test_ml_model.py::test_scoring_is_deterministic_given_fixed_seed`.
