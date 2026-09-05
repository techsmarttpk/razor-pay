# context.md — current state snapshot

Last updated: 2026-09-04, end of the initial autonomous build session.

## Current product vision

Razorpay Financial Control Agent (Track 04 + Track 03 outcome). Full detail
in claude.md and docs/architecture.md. Not a reconciliation product —
detect/diagnose/quantify money at risk, recommend, bounded-execute, audit.

## Current repository state: MVP complete and verified working

- Backend: FastAPI app, all endpoints implemented, 32 tests passing.
- Frontend: React/Vite app, all 8 primary pages + chat, `npm run build`
  passes clean (no TS errors).
- Dataset: seeded, 11,398 payments, 45 merchants, 963 ground-truth labels.
- Pipeline: runs end-to-end (detect → diagnose → act → audit → evaluate) in
  ~4 seconds.
- Evaluation: real numbers on held-out split — precision 1.00, recall 0.77,
  F1 0.87, FPR 0.00, root-cause accuracy 0.96, auto-resolution precision
  1.00, MAPE 0.3%, throughput ~4,600 records/sec.
- **Manually verified in-browser** (Chrome via claude-in-chrome tools):
  Overview, Exceptions list, Exception detail (full WHY→EVIDENCE→
  CALCULATION→ROOT CAUSE→DECISION→ACTION→RESULT chain, including a
  multi-hypothesis settlement_variance case), live action execution
  (ESCALATE button updated status + audit trail in real time), Money at
  Risk (chart + list), Recovery/Actions (table, after fixing a stale-backend
  404 — see below), Agent Investigation chat (deterministic answer, correct
  numbers). Model Performance page confirmed showing real, non-hardcoded
  metrics.

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
- [x] Tests pass (32/32)
- [x] README usable (setup, quick start, architecture summary, latest metrics)
- [x] claude.md exists and current
- [x] context.md exists and current (this file)

## Important files (see claude.md for full map)

- `backend/app/services/data_generator.py` — dataset + ground truth
- `backend/app/analytics/detectors.py` — detection engines
- `backend/app/agents/root_cause.py` — diagnostic tree (waterfall allocator)
- `backend/app/agents/action_engine.py` — bounded action allowlist + categorization
- `backend/app/services/pipeline.py` — orchestration
- `backend/app/services/evaluation.py` — held-out scoring
- `backend/app/api/routes.py` — all API endpoints
- `frontend/src/pages/ExceptionDetailPage.tsx` — the core demo screen
- `frontend/src/index.css` — the entire design system

## Last successful commands (in order, this session)

```
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
```

## Current test status

32/32 backend tests passing. No frontend unit tests were written (time
budget went to the browser-verified manual walkthrough instead — this was a
deliberate tradeoff given the hackathon time constraint, not an oversight;
flagged here so a future session knows it's a gap, not a failure).

## Known bugs (all fixed — see claude.md "Known bugs found and fixed this
session" for full detail): root-cause waterfall double-counting, duplicate
detector grouping key, repeated_cohort_anomaly label/detector key mismatch,
refund_rate_spike z-score threshold, dataset volume scaling. All five were
caught either by the test suite or by inspecting `by_scenario` in the
evaluation output, then fixed and re-verified.

## Current known gaps / honest limitations

- `refund_rate_spike` and `merchant_level_anomaly` currently show 0/2
  detected on the committed holdout run — small sample size (2-6 carrier
  merchants), genuinely hard, reported honestly rather than tuned to look
  better. A future session could add more carrier merchants or refine the
  isolation-style scoring if this matters for a specific demo audience.
- No Postgres run yet (SQLite only, though the abstraction is there).
- `RazorpayTestModeProvider` is an unwired stub (see claude.md).
- Frontend JS bundle is a single 692KB chunk — no code splitting.
- This directory is **not a git repository** — no commits exist. If the
  user wants version control, `git init` needs to happen first (not done
  automatically per the safety guidelines — destructive/setup git actions
  need explicit confirmation, and repo init wasn't explicitly requested).

## Immediate next actions (if resuming)

1. Confirm whether the backend/frontend dev servers from this session are
   still running (`netstat -ano | grep :8000` / `:5174` on Windows) or need
   restarting — see Quick Start in README.md.
2. If asked to make the demo "sharper," the highest-leverage next step is
   probably improving `refund_rate_spike`/`merchant_level_anomaly` recall
   (currently the two weakest scenario types) or adding a couple more
   carrier merchants to shrink evaluation noise.
3. If asked to add git, run `git init` + initial commit only after explicit
   user confirmation (per the standing safety guidelines in this
   environment), then this context.md/claude.md pair should get a "git
   history now available, prefer `git log` over this snapshot for recent
   changes" note added to context.md's top.

## Assumptions a future session must preserve

- **No real money movement, ever.** The action allowlist in
  `action_engine.py` is the safety boundary — do not add an action type that
  performs an irreversible financial operation.
- **The LLM never computes a financial amount.** All amounts flow from
  deterministic code in `detectors.py`/`root_cause.py`; `llm.py` only
  phrases already-computed facts.
- **Evaluation must stay held-out.** Never let `run_evaluation()` score
  against the `calibration` split, and never hand-edit
  `data/benchmarks/results.json`.
