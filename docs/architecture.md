# Architecture

## Pipeline

```
synthetic/mock Razorpay data (SQLite)
        |
        v
DataBundle (pandas, app/repositories/data_repo.py)
        |
        v
11 detectors (app/analytics/detectors.py)
  - fee anomaly (robust z-score) + repeated cohort rollup
  - delayed settlement (rule)
  - refund timing mismatch (join)
  - duplicate transaction (same-order window rule)
  - missing settlement item (rule)
  - partial settlement (rule)
  - settlement variance (bank vs settlement join)
  - chargeback reserve (rule)
  - refund rate spike (EWMA-style baseline + z-score)
  - settlement degradation (linear trend slope)
  - merchant-level anomaly (isolation-style z-score over merchant-day features)
        |
        v  Finding {exception_type, entity, money_at_risk, breakdown, evidence, confidence}
        |
        v
Root-cause engine (app/agents/root_cause.py)
  - unambiguous types: detector's classification IS the root cause
  - settlement_variance: waterfall-allocates the fixed variance across
    refund_timing -> fee_anomaly -> chargeback_reserve -> delayed_settlement
    -> unknown/unresolved, strongest evidence first, never exceeding the
    total (each hypothesis capped at remaining budget)
        |
        v  Diagnosis {hypotheses, contradicted, calculations, confidence, final_classification}
        |
        v
Bounded action engine (app/agents/action_engine.py)
  - categorize(): SAFE_AUTO_ACTION / REVIEW_REQUIRED / ESCALATE
    (deterministic function of confidence, amount, and whether the
    classification actually resolved)
  - recommend_action(): fixed exception_type -> action_type map,
    every action asserted to be in an 8-item allowlist
        |
        v
Pipeline (app/services/pipeline.py)
  - persists Exception + Action rows
  - executes SAFE_AUTO_ACTION immediately (idempotent, keyed by
    exception_id:action_type)
  - leaves REVIEW_REQUIRED/ESCALATE pending for operator action
  - writes an append-only AuditEvent for every decision
  - calls the LLM layer only to phrase the explanation text (all numbers
    already computed)
        |
        v
Evaluation (app/services/evaluation.py)
  - scored only on the `holdout` ground-truth split
  - precision/recall/F1/FPR, root-cause accuracy, money-at-risk MAPE,
    auto-resolution precision, throughput, per-scenario detection rate
        |
        v
FastAPI (app/api/routes.py) -> React dashboard
```

## Why a waterfall for settlement variance

A settlement's bank-credit shortfall (`variance`) is a *fixed pot of money*.
Multiple candidate causes (unreflected refunds, fee excess, chargeback
reserves) can each independently sum to more than the variance — that just
means they're strong signals, not that they get to claim more rupees than
exist. `diagnose_settlement_variance` allocates strongest-evidence-first,
capping each hypothesis at whatever budget remains, so allocated components
always sum exactly to the variance (raw, uncapped signal strength is kept in
`raw_amount` for transparency in the evidence panel). This was a real bug
caught by `tests/test_root_cause.py::test_settlement_variance_diagnosis_shape`
during development — see claude.md.

## Why detection engines never double-count money

Each detector operates on a disjoint pool of source entities/components by
construction of both the generator and the detectors:
- `fee_anomaly` money comes from `payment.fee - payment.expected_fee`.
- `delayed_settlement` money is the settlement's own amount, tagged only
  when delay >= 4 days.
- `refund_timing_mismatch` money comes from refunds NOT reflected in any
  settlement item.
- `settlement_variance` money is `settlement.amount - bank_transaction.amount`
  — a residual that in the synthetic generator is injected as a pure,
  unrelated deduction, independent of fee/refund events.

This is a deliberate simplification for the hackathon MVP: it avoids
double-counting by keeping each detector's money source disjoint rather than
implementing a fully general cross-exception deduplication pass. See
`app/services/overview.py` for how these are summed at the portfolio level.

## Provider abstraction

`app/providers/razorpay_provider.py` defines `RazorpayProvider` with two
implementations: `MockRazorpayProvider` (reads the synthetic dataset —
used everywhere in this build) and `RazorpayTestModeProvider` (a structured
stub showing exactly where real `razorpay-python` SDK calls would go, gated
on `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`, never called without them). The
rest of the system only ever talks to `DataBundle`, so swapping providers
requires no changes downstream.

## LLM abstraction

`app/agents/llm.py` defines `LLMProvider` with `DeterministicTemplateProvider`
(default — pure string templating over already-computed facts) and
`AnthropicProvider` (used only if `ANTHROPIC_API_KEY` is set; falls back to
the deterministic provider on any error). The system prompt for the
Anthropic path explicitly forbids introducing any number not present in the
JSON facts payload.
