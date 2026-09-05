# Deck Notes — Financial Control Agent Investor Briefing

Companion notes for `Financial_Control_Agent_Investor_Deck.pptx` (12 slides). For each slide: purpose, the one thing to say, the evidence it's built on, and whether the content is a **present-tense fact** (verified in the repository) or a **future projection** (explicitly labeled as such on the slide itself).

---

## Slide 1 — Title: "Financial Control Agent"

**Purpose:** Open with the product's real identity and immediately disclose its current limits, before any hype can build.

**Key talking point:** This is a running, tested system — not a mockup — but it has never touched a live processor. Say the disclosure line ("Prototype system · evaluated on synthetic, Razorpay-shaped merchant data · not yet connected to a live processor") out loud as part of the opening, not as a footnote to be discovered later.

**Evidence/source:** README.md title/positioning; `app/main.py` FastAPI app title; `data/synthetic/meta.json` (45 merchants, 11,398 payments); `ALL_DETECTORS` in `backend/app/analytics/detectors.py` (11 entries); 53 passing tests (`grep -h "^def test_" backend/tests/*.py | wc -l`).

**Status:** Fact. All four stat chips and the disclosure line are directly verifiable in the repository.

---

## Slide 2 — The Problem: "Where money at risk goes invisible"

**Purpose:** Establish the gap the product fills, in the investor's own mental model of a payment lifecycle, before showing any product.

**Key talking point:** Walk Payment → Settlement → Refund/Dispute → Ledger Close left to right, then point at the gap between Settlement and Refund/Dispute: reconciliation tells you the ledger doesn't balance, not which transaction, how much, or why. The four pain points underneath are the analyst's actual daily workflow today.

**Evidence/source:** Framing drawn from `docs/architecture.md` and README.md ("not a reconciliation product"). This slide is scene-setting / problem framing, not a repository metric.

**Status:** Contextual framing, not a data claim — no numbers on this slide to verify.

---

## Slide 3 — The Product: "One pipeline: from raw data to a safe, logged action"

**Purpose:** Show the entire product in one row. This is the single slide an investor should remember.

**Key talking point:** Read the seven words (DATA → DETECTION → MONEY AT RISK → ROOT CAUSE → DECISION → ACTION → AUDIT), then the seven phrases underneath. Each one names a real, running function — not an aspiration.

**Evidence/source:** `backend/app/services/pipeline.py::run_full_pipeline` (orchestrates exactly these seven stages); `ALL_DETECTORS` (11 entries, `backend/app/analytics/detectors.py`); `ALLOWED_ACTIONS` (8 items, none move money, `backend/app/agents/action_engine.py`); `AuditEvent` ORM model (append-only audit row per decision, `backend/app/models/orm.py`).

**Status:** Fact. Every stage name maps to a specific function or module in the codebase today.

---

## Slide 4 — Architecture: "Where the intelligence actually lives"

**Purpose:** Give a technical investor the real system diagram, with an explicit legend distinguishing data, deterministic logic, ML, and LLM — so no one mistakes the LLM for a decision-maker.

**Key talking point:** Read the legend first. Trace the row: synthetic data → SQLite → 13 engineered features → 10 rule detectors and the one trained Isolation Forest → deterministic OR-ensemble → root cause → action engine → optional Claude narration → served by FastAPI/React. The amber callout is the single most important sentence on this slide: Claude never computes an amount, chooses a root cause, or executes an action.

**Evidence/source:** `backend/app/repositories/data_repo.py`; `backend/app/analytics/{detectors.py, features.py}`; `backend/app/ml/anomaly_model.py`; `backend/app/agents/{root_cause.py, action_engine.py, llm.py}`; `backend/app/api/routes.py`; `frontend/src`. The Razorpay-stub caveat is verified directly: `get_provider()` in `backend/app/providers/razorpay_provider.py` has no callers anywhere else in the codebase (`grep -rn "get_provider\b" app/`).

**Status:** Fact. Every node and every disclaimer on this slide is independently verifiable by reading the named files.

---

## Slide 5 — The Intelligence Layer: "Three layers of intelligence — one hard boundary"

**Purpose:** Pre-empt the "where is the AI" question directly, with three honest categories instead of one vague "AI" claim.

**Key talking point:** Statistical intelligence is auditable constants, not learned weights. ML intelligence is a real trained model, but scoped to exactly one detector (merchant-day behavioral anomaly). Generative AI narrates already-computed facts — it does not compute anything. Close on the design principle: "ML detects. Deterministic controls decide. LLM explains."

**Evidence/source:** `backend/app/analytics/detectors.py` (10 rule/statistical detectors); `backend/app/ml/anomaly_model.py` + `backend/app/analytics/features.py` (13 features, `time_split()` train/score separation); `backend/app/agents/llm.py` (the `AnthropicProvider` system prompt forbids introducing new numbers; `DeterministicTemplateProvider` is the default/fallback with no API key configured).

**Status:** Fact. Includes the honest disclosure that no API key is configured in this build, so the template narration path runs, not the live Claude call.

---

## Slide 6 — One Anomaly End to End: "One merchant. One anomaly. Eight steps to a logged decision."

**Purpose:** Make the pipeline concrete with a single walked-through case, using the system's real function and threshold names — feels like a demo, not an architecture lecture.

**Key talking point:** Tell it as a story: a merchant's refund rate quietly climbs past a stable 50-day baseline, crosses a hard threshold, gets detected by both a rule and the ML ensemble, gets a root cause, gets routed to review, and is logged. Every noun on this slide is a real function or threshold in the code.

**Evidence/source:** `backend/app/analytics/detectors.py::detect_refund_rate_spike`; `backend/app/rules/thresholds.py` (`REFUND_SPIKE_MIN_RATIO=2.5`, `REFUND_SPIKE_MIN_Z=1.2`); `backend/app/analytics/features.py` (`refund_rate_z30`, `fee_excess_ratio`, `avg_delay_days`); `backend/app/analytics/detectors.py::detect_merchant_level_anomalies_ensemble`; `backend/app/agents/root_cause.py::diagnose`; `backend/app/agents/action_engine.py` (`REVIEW_REQUIRED` category, `generate_merchant_alert` action); `backend/app/models/orm.py::AuditEvent`.

**Status:** Illustrative but grounded — explicitly labeled on-slide as "illustrative run through the pipeline's own detector and threshold logic," not a captured screen recording. No live app screenshot was used because the app was not reachable with browser access in this environment; a narrated walkthrough was used instead of fabricating a screenshot.

---

## Slide 7 — Proof / Results: "Measured on a held-out set the thresholds never saw"

**Purpose:** Show real evaluation numbers — and immediately disclose the one place they are weak, before an investor has to ask.

**Key talking point:** Lead with dataset scale (45 merchants, 11,398 payments, 16 anomaly scenarios, 307 holdout labels, 53 backend tests), then the strong system-wide numbers (precision 100%, recall 77%, F1 87%, FPR 0%). Then pivot immediately to the chart: the one place ML is genuinely head-to-head tested against rules, results are weak and the sample is tiny (6 positive / 12 negative holdout merchants). Say the sample-size caveat out loud before being asked.

**Evidence/source (verified against the JSON directly, not README rounding):** `data/benchmarks/results.json` — precision 1.0, recall 0.7714, f1 0.871, false_positive_rate 0.0, root_cause_accuracy 0.9556, money_at_risk_mape 0.0035, processing_throughput_records_per_sec 4197.0, by_scenario.fee_anomaly.detection_rate 0.62, by_scenario.settlement_variance.detection_rate 0.462. `data/benchmarks/ml_comparison.json` — `existing_rules_combined` (P 0.40 / R 0.333 / F1 0.364 / FPR 0.25), `isolation_forest` (P 0.30 / R 0.50 / F1 0.375 / FPR 0.583), `ensemble_rules_or_ml` (P 0.333 / R 0.667 / F1 0.444 / FPR 0.667), `evaluation_population` (6 positive / 12 negative merchants).

**Status:** Fact, with the weak result explicitly surfaced rather than hidden. The on-slide disclaimer ("Early directional benchmark... Not statistically powered; not production-ready") is load-bearing — do not skip it when presenting.

---

## Slide 8 — Why The Architecture Matters: "Five things a red dot on a dashboard doesn't give you"

**Purpose:** Make the case that the five capabilities (Detect / Quantify / Explain / Act / Audit), taken together, are the differentiator — not any single one.

**Key talking point:** All five rows are true simultaneously in the running code today; that combination is the argument. Contrast against a plain anomaly-detection dashboard that can only say "something looks weird" — described generically, not naming any competitor.

**Evidence/source:** Synthesizes sections 2–5 of this same deck; `backend/app/services/pipeline.py` ties all five behaviors together on every run.

**Status:** Fact (as a description of what the running pipeline does), framed as a competitive argument rather than a benchmarked claim against any named competitor.

---

## Slide 9 — Reality Check: "What's real today — and what isn't yet"

**Purpose:** The credibility hinge of the whole deck. State plainly, side by side, what is proven and what is not — this is the slide a technical investor will use to decide whether to trust everything else.

**Key talking point:** Present this plainly and do not rush the right-hand column. Every REAL TODAY item is independently verifiable by reading the repository. Every NOT YET item is a real, named gap, not a hidden one — and it maps directly onto the Roadmap slide that follows.

**Evidence/source:** Full repository read (`backend/app`, `frontend/src`) for the REAL column. For NOT YET: `backend/app/providers/razorpay_provider.py` (`RazorpayTestModeProvider` raises `NotImplementedError`; `get_provider()` uncalled elsewhere in the codebase); synthetic-only dataset (`data/synthetic/`, `data_generator.py`); `ml_comparison.json` evaluation population of 18 merchants total.

**Status:** Fact on both sides — this slide exists specifically so nothing here is a projection.

---

## Slide 10 — Business Opportunity: "Who this is for — and what it removes"

**Purpose:** Name the buyer types and the value proposition in product/technical terms, without inventing market data that doesn't exist.

**Key talking point:** The buyer list (payment processors, fintechs, marketplaces, merchant platforms, financial ops teams) is derived from the problem the product actually solves — nobody has said yes yet. Say the disclaimer line out loud before an investor asks about TAM; volunteering it lands better than being asked.

**Evidence/source:** Market hypothesis grounded in the problem statement (`docs/architecture.md`, README.md) — not a figure present anywhere in the repository.

**Status:** Future / hypothesis, explicitly labeled on-slide: "Market sizing, pricing, and customer traction are not yet established — this reflects product and technical positioning only, not validated go-to-market data." No TAM, revenue, customer count, or traction figures are stated anywhere on this slide.

---

## Slide 11 — Roadmap: "What's proven, what's next"

**Purpose:** Turn the Reality Check's "NOT YET" column into a sequenced plan, without pretending any stage past NOW has started.

**Key talking point:** Only NOW is filled in with a solid marker, because it's the only stage with evidence behind it today. NEXT / THEN / SCALE are explicitly future and unproven — shown with hollow markers on purpose. The gate between every stage is the same discipline used to produce this deck: re-run the evaluation pipeline and report the numbers exactly as they come out.

**Evidence/source:** Sequence follows directly from the NOT YET column on the Reality Check slide (`razorpay_provider.py` stub, synthetic-only dataset, no deployment).

**Status:** Future projection, explicitly and visually distinguished from NOW (solid vs. hollow markers) — no dates or funding-dependent commitments are stated.

---

## Slide 12 — Investment Thesis: "The control layer between payment data and financial operations"

**Purpose:** Close the pitch by naming exactly what's proven, what isn't, and what investment specifically unlocks — then land the one sentence the deck is built to earn.

**Key talking point:** Close on the reproducibility line — it's the single strongest credibility claim in the deck, and it's true: every metric shown traces to `data/benchmarks/results.json` or `ml_comparison.json`, regenerated by the repository's own evaluation pipeline. Deliberately no "Thank You" slide — end here and take questions.

**Evidence/source:** Synthesizes Slides 3–9 and 11 of this deck. The three-card summary (proven / unproven / unlocked) restates Reality Check and Roadmap in investment-decision terms rather than introducing new claims.

**Status:** Mixed by design and labeled per card — "What we've proven" is fact, "What remains unproven" is an honest gap list, "What investment unlocks" is a future projection tied to the Roadmap's NEXT/THEN stages.

---

## Numbers used in this deck, at a glance (all traceable to the repository)

| Metric | Value | Source |
|---|---|---|
| Merchants | 45 | `data/synthetic/meta.json` |
| Payments | 11,398 | `data/synthetic/meta.json` |
| Detectors | 11 (in `ALL_DETECTORS`) | `backend/app/analytics/detectors.py` |
| Backend tests passing | 53 | `grep -h "^def test_" backend/tests/*.py \| wc -l` |
| Anomaly scenarios | 16 | `data/benchmarks/results.json` |
| Holdout labels (system-wide) | 307 | `data/benchmarks/results.json` |
| Precision / Recall / F1 / FPR (system-wide) | 100% / 77% / 87% / 0% | `data/benchmarks/results.json` |
| Root-cause accuracy | 96% (on true positives caught) | `data/benchmarks/results.json` |
| Money-at-risk MAPE | 0.35% | `data/benchmarks/results.json` |
| Throughput | ~4,200 records/sec | `data/benchmarks/results.json` |
| Merchant-anomaly holdout population | 6 positive / 12 negative merchants | `data/benchmarks/ml_comparison.json` |
| Rules-only / Isolation Forest / Ensemble (P/R/F1/FPR) | 40/33.3/36.4/25 · 30/50/37.5/58.3 · 33.3/66.7/44.4/66.7 | `data/benchmarks/ml_comparison.json` |

No number above was rounded up, cherry-picked, or restated more favorably than the underlying JSON. Where a metric is weak (merchant-level anomaly detection on 18 total merchants), the deck states it and the sample size in the same breath, on Slide 7.
