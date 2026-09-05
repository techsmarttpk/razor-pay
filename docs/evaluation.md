# Evaluation methodology

## Ground truth generation

`backend/app/services/data_generator.py` injects 16 scenario types into an
otherwise-plausible synthetic Razorpay merchant dataset and records a ground
truth label for every injection: `merchant_id`, `scenario_type`,
`entity_type`/`entity_id` (what the detector should point at),
`expected_amount` (where a single-entity amount is well-defined),
`is_true_anomaly` (false for the two benign/negative scenarios), and a
`split` of `calibration` or `holdout`.

Each label is independently assigned to `calibration` (70%) or `holdout`
(30%) at generation time. Merchant-level/cohort scenarios (only a handful of
carrier merchants each) use a forced alternating split instead of a random
draw, specifically so every scenario type is guaranteed at least one holdout
instance — with only 2-6 merchants per scenario, a random 70/30 draw could
easily place zero of them in holdout by chance, leaving that scenario type
unevaluated. This does not affect detector thresholds, only which split a
given label's own outcome contributes to.

## What each split is for

- **`calibration`** (605-655 labels depending on regeneration): used only to
  sanity-check the constants in `app/rules/thresholds.py` while building the
  detectors. These are plain, auditable constants — not learned weights.
- **`holdout`** (~300 labels): **never** used to pick a threshold. This is
  the only split `app/services/evaluation.py` scores against.

## Metrics computed

For every holdout label, `run_evaluation()` checks whether any persisted
`Exception` row matches on `entity_id` and (`exception_type` OR
`root_cause_label`) equal to the label's `scenario_type`:

- **True anomaly + match** → true positive. Root-cause accuracy is scored
  strictly (root_cause_label must equal scenario_type exactly). Money-at-risk
  error is scored where `expected_amount > 0`.
- **True anomaly + no match** → false negative (missed).
- **Benign/negative + match** → false positive.
- **Benign/negative + no match** → true negative.

From this: precision, recall, F1, false-positive rate, root-cause accuracy,
money-at-risk MAPE, auto-resolution precision (of auto-resolved exceptions
matched to a holdout label, what fraction were true positives), and
processing throughput (a fresh timed run of all detectors over the full
dataset).

## Reading the numbers honestly

- **100% precision, 0% FPR** on this seed means the detectors did not fire
  incorrectly on any of the ~250 holdout negative labels (127 normal_exact_match
  + benign false-positive injections). That's a real, checkable result — not
  a claim that false positives are architecturally impossible.
- **~77% recall** is not padded to look better. `fee_anomaly` (~62%) and
  `settlement_variance` (~46%) are the weakest categories — small-value fee
  overcharges below the `FEE_ANOMALY_MIN_ABS` threshold are deliberately not
  flagged (chasing sub-₹8 noise isn't worth an operator's attention), and
  ambiguous settlement variance is intentionally hard to fully explain from
  three candidate hypotheses.
- **Root-cause accuracy ~96%** is scored only on the true positives that
  were actually detected (`root_cause_evaluated_on`), so it says "when we
  caught it, we usually diagnosed it correctly" — not "we diagnose 96% of
  all anomalies correctly."

Re-run `python -m app.services.seed` any time to regenerate a fresh dataset
and get fresh (deterministic, seed=42) numbers — nothing in
`data/benchmarks/results.json` is hand-edited.

## ML model evaluation (Isolation Forest)

The rule/statistical evaluation above scores the whole pipeline. The one ML
model in the codebase (`app/ml/anomaly_model.py`) gets its own, stricter
held-out procedure, because an unsupervised model needs a genuine
train/inference split, not just a label split:

1. **Time-based train/score split**, not a random one. The generator only
   ever injects the three merchant-level scenario types
   (`merchant_level_anomaly`, `refund_rate_spike`, `settlement_degradation`)
   into the final 10 simulated days (`data_generator.py`'s `is_last10`).
   `time_split()` fits the Isolation Forest exclusively on the days before
   that window and scores only the days at/after it — the model never sees
   a row it is later evaluated on, in either direction.
2. **Threshold selection** scans candidate anomaly scores on the
   `calibration`-split carrier merchants (plus a deterministically-hashed,
   disjoint calibration half of the merchants that carry no merchant-level
   label at all) and picks the F1-maximizing cutoff. This is the direct ML
   analogue of how `app/rules/thresholds.py`'s constants were sanity-checked
   against calibration data — a number derived from data, frozen before
   touching holdout.
3. **Final metrics** use ONLY the `holdout`-split carrier merchants plus the
   other (disjoint) half of the never-anomalous pool — see
   `run_comparison()` in `app/ml/anomaly_model.py`.
4. **Contamination (0.03)** is a documented assumption, not a fitted
   parameter: ~18 of 45 merchants ever carry a merchant-level anomaly label,
   each active for only their final 10 days, against ~2,250 total training
   merchant-days — 3% is a deliberately conservative estimate of that noise
   floor plus a margin for instance-level scenarios landing in the training
   window, not a value tuned to make the numbers look good.

**Reading the ML numbers honestly**: the holdout population here is tiny —
6 positive merchants (2 per scenario type) and 12 negative ones. Every
percentage point in `data/benchmarks/ml_comparison.json` represents roughly
one merchant, so these results are directional evidence that a joint
multivariate model catches scenarios the univariate rules miss (concretely,
in the committed run: the Isolation Forest catches both `refund_rate_spike`
holdout carriers that the existing rules — including that scenario's own
dedicated detector — miss), not a statistically powered claim. The
comparison table intentionally reports precision/recall/F1/FPR for the
existing rules, the single heuristic being replaced, the Isolation Forest
alone, and the safe OR-ensemble side by side, computed identically for all
four, so nothing is cherry-picked.
