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
- **Merchant-level scenarios (refund_rate_spike, merchant_level_anomaly)
  have low sample counts** (2-6 carrier merchants each) and correspondingly
  noisy holdout recall (currently 0/2 and 0/2 on the committed benchmark
  run) — genuinely hard to detect reliably from so few instances, reported
  honestly rather than hidden or inflated.
- **RazorpayTestModeProvider is a structured stub, not a working
  integration** — no credentials were available or required; it documents
  exactly where real `razorpay-python` SDK calls would go.
- **No Postgres tested** — `DATABASE_URL` env var swap is wired
  (`app/core/db.py`) but only SQLite has actually been run.
- **Frontend has one large JS chunk** (692KB, vite warns >500KB) — no
  code-splitting was done; acceptable for a demo, would matter for
  production.

## Commands

```bash
# Backend setup + seed (from backend/)
python -m venv venv
./venv/Scripts/pip install -r requirements.txt
./venv/Scripts/python -m app.services.seed        # regenerate data + rerun pipeline + evaluation

# Run API
./venv/Scripts/python -m uvicorn app.main:app --port 8000

# Tests
./venv/Scripts/python -m pytest tests/ -q          # 32 tests, requires a seeded DB

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
  it (both currently `assert`/400 on anything outside the set).

## Next session should inspect first

1. `data/benchmarks/results.json` — is it stale relative to the code? If
   thresholds or the generator changed, re-run the seed command.
2. `context.md` — the current-state snapshot, updated more frequently than
   this file.
3. Whether the user wants a git repo initialized (this directory was NOT a
   git repository as of this session — no commits exist anywhere).
