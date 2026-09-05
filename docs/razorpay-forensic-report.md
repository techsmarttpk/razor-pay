# Forensic Analysis — `razor-pay` Repository (D:\Projects\razor-pay)

Analysis date: 2026-09-05. Method: read every backend Python module and every frontend page/service file in full, traced imports/call graphs, grepped for model/mock/random/hardcode terms, cross-checked README/claude.md/context.md claims against `data/benchmarks/results.json` and actual source. No files were modified. Test execution was not attempted because it would have required installing Python packages (fastapi/pandas/sklearn are not present in the shell used), which the investigation rules prohibit — this is noted explicitly rather than silently skipped.

---

# 1. Executive Summary

This is a full-stack demo/hackathon project called the "Razorpay Financial Control Agent." It is a **rule-based and statistical anomaly-detection system**, not a machine-learning product, despite the "AI Finance Controller" framing. A FastAPI backend runs 11 deterministic/statistical detectors over a synthetic Razorpay-style dataset (payments, settlements, refunds, disputes, bank transactions), computes exact rupee amounts at risk via plain arithmetic, runs a rule-based root-cause "waterfall" allocator for ambiguous cases, categorizes each finding into an action tier via a deterministic function, and optionally phrases the result in English via a real Claude API call (or a string-template fallback if no API key is present). A React/TypeScript dashboard reads all of this from real backend endpoints — nothing in the frontend is faked or bypasses the API. The project is unusually well self-documented (`claude.md`, `context.md`) and, on independent verification, the documentation's factual claims about what the code does check out.

# 2. Actual Objective

The problem: a payments company's finance/ops team needs to know, at any moment, how much money is at risk across its merchants (unsettled funds, fee overcharges, duplicate charges, chargebacks, refund timing mismatches, etc.), why, and what to do about it — not just "these two ledgers don't match."

Intended workflow: generate/ingest transaction data → run detectors that flag specific financial anomalies with an exact evidence trail → for ambiguous cases, run a root-cause engine that apportions the exact variance amount across competing explanations → classify each finding by confidence/amount into "auto-resolve safely," "needs human review," or "escalate" → execute the safe, reversible actions (status flips, draft alerts, journal suggestions — never real money movement) → log every step to an append-only audit trail → surface all of it, plus a precision/recall benchmark against held-out ground truth, in a dashboard.

Input: Razorpay-shaped merchant financial data (currently 100% synthetic, generated in-repo with a fixed seed; a stub exists for real "Razorpay Test Mode" API data but is never invoked). Output: a set of "Exception" records (money at risk, root cause, confidence, recommended/executed action) exposed via a REST API and rendered in a dashboard, plus a JSON evaluation report.

In one paragraph for another developer: this is a synthetic-data financial-anomaly-detection demo. It generates fake but structurally realistic Razorpay merchant data with known injected anomalies, runs a bank of hand-written statistical detectors (z-scores, EWMA-style trend slopes, rule thresholds, one hand-rolled "isolation-style" z-score — not actual sklearn IsolationForest) to find them, computes exact money-at-risk figures by arithmetic (never estimated by an LLM), classifies and takes bounded, reversible actions via deterministic rules, and narrates the results either with string templates or, if you supply an API key, real Claude calls that are only allowed to rephrase numbers that already exist. It ships with a genuine train/holdout evaluation harness that reports real precision/recall/F1 against its own injected ground truth.

# 3. Is There a Real Model?

**PARTIALLY REAL / MOSTLY NO REAL ML MODEL.**

- There is **one real ML algorithm imported into the codebase**: `sklearn.ensemble.IsolationForest`, wrapped in `backend/app/analytics/stats.py::isolation_forest_scores()`. However, this function is **imported but never called anywhere in the codebase** (verified by `grep -rn "isolation_forest_scores"` — it appears only in its own definition and in an unused import line in `detectors.py`). It is dead code.
- The detector that is *named* as if it uses this model — `detect_merchant_level_anomalies` (exception type `merchant_level_anomaly`, detector name literally `"isolation_style_zscore"`) — does **not** call IsolationForest at all. It hand-computes `z_ticket` and `z_refund` (simple z-scores on average ticket size and refund rate) and combines them into a manual `anomaly_score = (z_ticket.clip(0) + z_refund.clip(0)) / 6.0`, thresholded against a constant in `thresholds.py`. This is honest about being "isolation-style" (i.e., inspired by, not literally using) in the README/docstrings, but it is worth flagging precisely because the unused import and the module docstring ("a thin isolation-forest wrapper") could mislead a reader into thinking a real model is scoring these anomalies.
- Every other one of the 11 detectors is pure statistics/rules: robust (median/MAD) z-scores, ratio/threshold rules, linear regression slope (`np.polyfit`) for trend detection, and set-based joins (duplicate detection, missing-settlement-item detection). None of these are "models" in the trained/learned-weights sense — thresholds are hand-picked constants in `rules/thresholds.py`, explicitly documented as "not learned weights."
- The one place a real generative model is genuinely wired in and actually invoked is `backend/app/agents/llm.py`: if `ANTHROPIC_API_KEY` is set, `AnthropicProvider` makes a real `anthropic.Anthropic().messages.create(model="claude-sonnet-5", ...)` call. This is real inference against a real hosted LLM — but its only job is to **phrase already-computed facts in English** (a strict system prompt forbids introducing any new number or cause), and it is not used for detection, classification, or risk quantification. If no key is present (the default, and the state of this environment — no `.env` or API key was found), a deterministic string-template class (`DeterministicTemplateProvider`) produces functionally identical output. So: no ML/AI is in the decision path; an LLM is optionally in the narration path only, and gracefully degrades to templates.

Bottom line: there is no trained model producing the risk scores, classifications, or dollar amounts shown in the UI. The "intelligence" is entirely deterministic code (arithmetic, thresholds, rule trees) plus one unused sklearn import. The only real model invocation anywhere is an optional Claude call used purely as a sentence generator.

# 4. End-to-End Data Flow

```
Synthetic data generation (offline, one-time or on-demand)
  backend/app/services/data_generator.py :: Generator.generate_dataset()
    → produces merchants/customers/orders/payments/refunds/settlements/
      settlement_items/disputes/fees/bank_transactions/ledger_entries
      + AnomalyLabel ground truth (16 injected scenario types,
        calibration/holdout split)
  backend/app/services/seed.py :: main()
    → writes CSVs to data/synthetic/ and data/ground_truth/
    → bulk-inserts into SQLite (data/fca.db) via SQLAlchemy models
      (backend/app/models/orm.py)
    → calls run_full_pipeline()

Detection pipeline (backend/app/services/pipeline.py :: run_full_pipeline)
  1. app/repositories/data_repo.py :: load_bundle()
       reads all SQLite tables into a DataBundle of pandas DataFrames
  2. app/analytics/detectors.py :: run_all_detectors(bundle)
       11 detector functions each scan the DataFrames and emit
       "Finding" dicts (exception_type, entity_id, money_at_risk,
       evidence, confidence, severity — all numeric fields computed
       by arithmetic on the actual data)
  3. app/agents/root_cause.py :: diagnose(finding, bundle)
       for settlement_variance/unresolved_exception: waterfall-allocates
       the exact variance amount across refund_timing → fee_anomaly →
       chargeback_reserve → delayed_settlement → unknown, using real
       joins against refunds/payments/disputes tables
       for all other types: passes the detector's own finding through
       unchanged (the detector's rule *is* the root cause)
  4. app/agents/action_engine.py :: categorize() + recommend_action()
       deterministic function of (money_at_risk, confidence,
       classification) → SAFE_AUTO_ACTION / REVIEW_REQUIRED / ESCALATE
       and one of 8 allowlisted action types
  5. app/agents/llm.py :: get_llm_provider().explain(facts)
       narrates the already-computed facts (template or real Claude call)
  6. Persisted as orm.Exception_, orm.Action, orm.AuditEvent rows in SQLite
  7. app/services/evaluation.py :: run_evaluation()
       re-runs detectors fresh (for throughput timing), scores
       Exception_ rows against the `holdout` split of AnomalyLabel,
       writes data/benchmarks/results.json

API layer (backend/app/api/routes.py, FastAPI, mounted in main.py)
  GET /api/overview, /api/exceptions, /api/exceptions/{id}, /api/actions,
  /api/events, /api/audit, /api/metrics, /api/merchants
  POST /api/exceptions/{id}/actions/{action_type}  (allowlist-checked)
  POST /api/pipeline/rerun
  POST /api/agent/ask  → app/services/overview.get_overview() facts
                          → llm_provider.answer() (same explain/template rules)
  All read straight from SQLite via SQLAlchemy/pandas — no caching layer,
  no stub responses.

Frontend (frontend/src, React+TS, axios via services/api.ts)
  Every page (OverviewPage, ExceptionsPage, ExceptionDetailPage,
  MoneyAtRiskPage, RecoveryActionsPage, AuditTrailPage,
  FinancialEventsPage, AgentInvestigationPage, ModelPerformancePage)
  calls the matching /api/* endpoint via services/api.ts and renders
  the response directly. Action buttons on ExceptionDetailPage POST to
  /api/exceptions/{id}/actions/{action_type} and re-fetch.

Output: dashboard showing money at risk, root-cause evidence chains,
audit trail, and a held-out precision/recall benchmark — all traceable
back to specific rows in the synthetic SQLite database.
```

# 5. REAL vs FAKE vs UNCLEAR

| Component | Status | Evidence | Explanation |
|---|---|---|---|
| ML model (IsolationForest) | **UNUSED / DEAD CODE** | `stats.py:34 isolation_forest_scores()`; grep shows zero callers | A real sklearn model is defined but never invoked anywhere in the running app. |
| "isolation_style_zscore" detector | **FAKE MODEL, REAL STATS** | `detectors.py` `detect_merchant_level_anomalies` | Named to evoke an isolation forest but is actually a hand-computed z-score sum. Not deceptive about the numbers (they're real), but the naming implies more ML than exists. |
| Other 10 detectors | **REAL (rule/statistical)** | `detectors.py` full file | Robust z-scores, ratio thresholds, linear regression slope, set joins — all computed from real synthetic data, no hardcoding of results. |
| Root-cause engine | **REAL (deterministic)** | `root_cause.py` | Waterfall allocation against actual refund/payment/dispute records; not an LLM guess. |
| Money-at-risk figures | **REAL (arithmetic)** | `detectors.py`, `root_cause.py` | Every amount traces to a `.sum()`/subtraction over real DataFrame columns; no random or fixed constants used as "results." |
| LLM narration | **REAL (optional) / templated (default)** | `agents/llm.py` | Real `anthropic` API call only if `ANTHROPIC_API_KEY` set (not set in this environment); otherwise a deterministic Python string template producing the same shape of text. Either way, LLM never invents a number. |
| Action engine / auto-execution | **REAL, but simulated-safe by design** | `action_engine.py`, `pipeline.py` | Actions are status flips / drafts / journal *suggestions* only — by explicit design no real money moves. This is a documented product safety constraint, not a hidden mock. |
| Razorpay integration | **NOT REAL / STUB, disconnected** | `providers/razorpay_provider.py`; `get_provider()`/`RazorpayTestModeProvider` never referenced elsewhere in repo | Entire provider abstraction is unused dead code; the app reads exclusively from the synthetic SQLite DB via `data_repo.py`, never through this provider layer. |
| Input/data | **SYNTHETIC (declared as such)** | `data_generator.py`, `data/synthetic/*.csv` | 100% generated data with a fixed seed; openly documented as synthetic in README/claude.md, not presented as live merchant data. |
| Backend API | **REAL** | `api/routes.py` | Every endpoint queries SQLite/SQLAlchemy; no hardcoded JSON responses found. |
| Frontend | **REAL** | `services/api.ts`, all `pages/*.tsx` | Every page fetches from a real backend endpoint; no client-side mock data, no `Math.random()`-generated display values found in a repo-wide grep. |
| Evaluation metrics | **REAL, computed** | `evaluation.py`, `data/benchmarks/results.json` (regenerated 2026-09-05, matches README's numbers within normal seed-driven variance) | Computed by scoring actual `Exception_` rows against a `holdout` label split never used for threshold tuning. |
| Tests | **REAL** | `backend/tests/*.py`, 32 `def test_` functions matching README's claimed count exactly | Substantive assertions against a live TestClient + seeded DB, not trivial smoke stubs. |

# 6. Model / AI Forensics

- **Model files**: none (no `.pt`/`.pth`/`.onnx`/`.h5`/`.joblib`/`.pkl` anywhere in the repo — confirmed by the file listing).
- **Model-loading code**: `stats.py::isolation_forest_scores()` instantiates and fits `sklearn.ensemble.IsolationForest` fresh on every call (it is not a persisted/pretrained model — it would retrain from scratch each time it's invoked). It is never invoked.
- **Inference code**: none for ML in the traditional sense. Statistical "inference" is scipy/numpy/pandas arithmetic (z-scores, EWMA, polyfit) inline in `detectors.py`. The only real inference call in the repository is the optional `anthropic.Anthropic().messages.create(...)` in `llm.py`, used solely for text generation, not decisioning.
- **Preprocessing**: `data_repo.py` parses datetime columns; detectors do their own feature engineering (excess fee, refund rate, delay days) inline in pandas.
- **Postprocessing**: `root_cause.py` and `action_engine.py` turn raw findings into classified, actioned records; `evaluation.py` turns them into precision/recall metrics.
- **Training code**: none exists for any model. `rules/thresholds.py` documents its constants as manually inspected against a "calibration" data split, explicitly *not* fitted/learned weights.
- **Connected to running app?**: IsolationForest — no. Claude LLM — yes, but gated behind an environment variable that is unset in this environment, so at runtime here it is not active; the deterministic template path runs instead.

# 7. Fake / Mock / Hardcoded Detection

1. **Dead ML import** — `analytics/stats.py::isolation_forest_scores` is imported into `detectors.py` (line 12) but never called. Anyone skimming the import list would reasonably believe merchant-anomaly detection uses IsolationForest; it does not.
2. **Misleadingly named detector** — `detect_merchant_level_anomalies`'s internal `detector` field is `"isolation_style_zscore"`, and the module docstring calls it "a thin isolation-forest wrapper." The actual computation is a manual sum of two clipped z-scores divided by 6 — a hand-tuned heuristic, not a model output, though it is at least computed live from real data rather than faked.
3. **Disconnected provider abstraction** — `providers/razorpay_provider.py` defines a full `RazorpayProvider` ABC, a `MockRazorpayProvider`, and a `RazorpayTestModeProvider` (whose methods explicitly `raise NotImplementedError`). Grep confirms `get_provider()` is called nowhere in the codebase; the real pipeline (`repositories/data_repo.py`) bypasses this layer entirely and reads SQLite directly. This is not deceptive — it's clearly labeled as a "structured stub, not wired to network calls" in both the code docstring and `claude.md` — but it is inert scaffolding, not an active integration, and a casual reader of the file alone could mistake it for a working Razorpay connector.
4. **Synthetic data used as "the" dataset** — `random`/`np.random` usage is confined entirely to `services/data_generator.py`, which is honestly documented as a synthetic generator with injected, labeled scenarios. This is not runtime fakery of results; it is the deliberate test-bed the detectors run against, and the generator explicitly notes "ground truth is for evaluation only," i.e. detectors never see the labels.
5. **No hardcoded predictions/confidences found** — grep for suspicious literals in the frontend and backend response paths found none; every number rendered in the UI (`ModelPerformancePage.tsx`, `OverviewPage`, exception detail) is fetched from a live API call, and the backend computes those numbers from the database on each request (or on each pipeline run for the benchmark file).
6. **LLM fallback is a legitimate safety design, not a hidden fake-out** — `AnthropicProvider.explain()`/`answer()` catch all exceptions and fall back to `DeterministicTemplateProvider`, but this fallback is documented in the docstring and does not misrepresent confidence or invent data; both paths only rephrase numbers computed elsewhere.

No instances were found of: hardcoded classifications, fake confidence scores, static JSON API responses, frontend values invented independently of the backend, or a "rule-based logic pretending to be ML" beyond item #2 above (which is a naming/documentation overstatement rather than a functional deception — the underlying numbers are real).

# 8. Architecture

Three tiers: (1) a synthetic-data generation/seed script that populates a local SQLite database (`data/fca.db`) with financial entities and ground-truth anomaly labels; (2) a FastAPI backend (`backend/app/`) organized into `repositories` (DB→pandas), `analytics` (statistical detectors), `agents` (root-cause diagnosis, bounded action engine, LLM narration), `services` (pipeline orchestration, KPI aggregation, evaluation), `models` (SQLAlchemy ORM), and `api` (REST routes) — all communicating in-process, no message queue or external service dependency; (3) a React 19 + TypeScript + Vite frontend that talks to the backend exclusively over HTTP (`axios`, proxied `/api` in dev) and renders 9 routes. There is no separate "AI service" — the LLM call, when active, happens inline inside the same FastAPI process during pipeline execution and during the `/api/agent/ask` request handler.

# 9. Dead / Disconnected / Broken Components

- `backend/app/analytics/stats.py::isolation_forest_scores()` — defined, imported, never called.
- `backend/app/providers/razorpay_provider.py` — the entire module (`RazorpayProvider`, `MockRazorpayProvider`, `RazorpayTestModeProvider`, `get_provider()`) is never imported by any other file in the repository; the actual data path goes through `repositories/data_repo.py` instead. Functionally dead scaffolding, honestly labeled as such in comments.
- `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` env vars — referenced only inside the dead provider module; have no effect on the running app.
- No frontend unit tests exist (`context.md` states this explicitly as a known, deliberate gap, not a hidden failure) — this is a documentation-confirmed gap rather than a discovered one, but it means the frontend's correctness rests only on the manually-noted browser walkthrough in `context.md`, which I could not independently re-verify without running the dev servers.
- Postgres support is wired via `DATABASE_URL` in `core/db.py` but never exercised — SQLite only, as `claude.md` itself states.

# 10. README/Documentation vs Reality

This repository's documentation (`README.md`, `claude.md`, `context.md`) is unusually accurate and self-critical compared to typical projects of this kind — it proactively discloses the synthetic dataset, the LLM-is-narration-only design, the unwired Razorpay stub, the two weak-recall scenario types, and the absence of frontend tests. Independent verification found no material discrepancy: test count (32), evaluation metric shape, and the "no ML black box" framing for detectors all matched what the code does. The one place documentation slightly overstates the sophistication of the implementation is the `stats.py` module docstring calling `isolation_forest_scores` "a thin isolation-forest wrapper" used by the pipeline, when in fact the pipeline's merchant-anomaly detector does not call it at all and instead uses a simpler hand-rolled z-score heuristic; the README's own bullet list is more careful, calling it "one lightweight isolation-style merchant-day anomaly score" rather than claiming IsolationForest is actually running — so the discrepancy is internal (docstring vs. actual behavior) rather than README vs. code.

# 11. Bottom Line

**What is this project?** A synthetic-data demo of a "financial control agent" for a payments company: it detects, quantifies, explains, and takes bounded action on money-at-risk anomalies in merchant transaction data.

**What is it supposed to do?** Continuously watch settlement/refund/fee/payment data, flag anomalies with an exact evidence trail, compute exactly how much money is at risk, diagnose why, auto-resolve the safe/high-confidence cases, escalate the rest, and log everything to an audit trail — while proving itself against a held-out labeled benchmark.

**What does it actually do right now?** Exactly that, end-to-end, against a self-generated synthetic dataset (~11,400 payments, 45 merchants, 16 injected anomaly scenarios). The pipeline runs, persists real results to SQLite, serves them over a real REST API, and a real React dashboard displays them. The benchmark file (`data/benchmarks/results.json`) shows it was actually re-run as recently as today (2026-09-05).

**Is a real ML/AI model running?** No trained model drives detection or risk quantification — that's all deterministic thresholds and arithmetic. A real `sklearn.IsolationForest` exists in the code but is dead/unused. The one real AI inference path is an optional Claude API call used strictly to phrase already-computed facts into sentences, and it isn't active by default (no API key configured here) — it silently degrades to string templates that produce equivalent output.

**Are any results fabricated/simulated?** The underlying *transaction data* is simulated (openly, by design — it's a demo/eval harness), but the *detection results, risk amounts, root causes, and evaluation metrics computed from that data* are all genuinely calculated, not fabricated on top of the simulation. Nothing found hardcodes an outcome independent of the data.

**Can I trust the displayed output?** Yes, in the sense that every number in the UI traces back through real code to real rows in the (synthetic) database — there is no faked shortcut in that chain. No, in the sense that the underlying data is not live/real Razorpay merchant data; treat this as a working proof-of-concept detection-and-control pipeline validated on synthetic ground truth, not as a system tested against real-world payment behavior.

**Biggest gaps between intended and actual:** (1) the "AI" framing oversells what is a rules/statistics engine — only text narration is LLM-backed, and only optionally; (2) the isolation-forest capability implied by imports/docstrings is unused; (3) there is no actual Razorpay integration — the provider abstraction is an unwired stub; (4) evaluation, while genuinely held-out, is scored against the same generator's own injected scenarios, so strong metrics reflect internal consistency between generator and detectors more than proof the detectors would generalize to real, unseen fraud/anomaly patterns; (5) no frontend automated tests exist.
