"""Deterministic + statistical detection engines.

Every detector returns plain "Finding" dicts. No LLM involvement here — all
amounts and evidence come straight out of the dataset. The LLM layer (see
app/agents/llm.py) only ever narrates findings that already exist.
"""
from datetime import timedelta

import numpy as np
import pandas as pd

from app.analytics.stats import robust_z
from app.analytics.features import build_merchant_day_features
from app.rules import thresholds as T

NOW = None  # set by pipeline to the dataset's "as of" timestamp


def severity_for(amount: float, confidence: float) -> str:
    if amount >= 100000 or (amount >= 40000 and confidence >= 0.85):
        return "critical"
    if amount >= 25000 or (amount >= 8000 and confidence >= 0.8):
        return "high"
    if amount >= 3000:
        return "medium"
    return "low"


def _finding(merchant_id, exception_type, entity_type, entity_id, detector,
             confidence, evidence, money_at_risk, recoverable_amount,
             breakdown, window_start, window_end, extra=None):
    return {
        "merchant_id": merchant_id,
        "exception_type": exception_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "detector": detector,
        "confidence": round(float(confidence), 3),
        "evidence": evidence,
        "money_at_risk": round(float(money_at_risk), 2),
        "recoverable_amount": round(float(recoverable_amount), 2),
        "money_at_risk_breakdown": breakdown,
        "severity": severity_for(money_at_risk, confidence),
        "window_start": window_start,
        "window_end": window_end,
        "extra": extra or {},
    }


# ---------------------------------------------------------------------------
# 1. Fee anomaly (+ repeated cohort anomaly rollup)
# ---------------------------------------------------------------------------
def detect_fee_anomalies(bundle):
    findings = []
    pay = bundle.payments.copy()
    if pay.empty:
        return findings
    pay["excess_fee"] = pay["fee"] - pay["expected_fee"]
    pay["excess_ratio"] = pay["excess_fee"] / pay["amount"].replace(0, np.nan)

    for merchant_id, grp in pay.groupby("merchant_id"):
        z = robust_z(grp["excess_fee"])
        grp = grp.assign(z=z)
        flagged = grp[
            (grp["excess_fee"] > T.FEE_ANOMALY_MIN_ABS)
            & (grp["excess_ratio"] > T.FEE_ANOMALY_MIN_RATIO)
            & (grp["z"] > T.FEE_ANOMALY_MIN_Z)
        ]
        for _, row in flagged.iterrows():
            confidence = min(0.98, 0.6 + min(row["z"] / 15, 0.35))
            findings.append(_finding(
                merchant_id, "fee_anomaly", "payment", row["id"], "fee_anomaly_zscore",
                confidence,
                evidence=[{
                    "type": "payment", "id": row["id"],
                    "summary": f"Fee ₹{row['fee']:.2f} vs expected ₹{row['expected_fee']:.2f} "
                               f"(baseline MDR) on ₹{row['amount']:.2f} order",
                    "fields": {"amount": row["amount"], "actual_fee": row["fee"],
                               "expected_fee": row["expected_fee"], "z_score": round(row["z"], 2)},
                }],
                money_at_risk=row["excess_fee"], recoverable_amount=row["excess_fee"],
                breakdown=[{"component": "excess_fee_charged", "amount": round(row["excess_fee"], 2),
                            "source_type": "payment", "source_id": row["id"]}],
                window_start=row["created_at"], window_end=row["created_at"],
            ))

    # cohort rollup: same merchant+method with sustained excess fee across
    # >=3 distinct days => repeated_cohort_anomaly (separate exception,
    # money already counted once at the payment level above is NOT re-added
    # here — this exception reports the pattern, not new money)
    pay["day"] = pay["created_at"].dt.date
    pay["cohort"] = pay["merchant_id"] + ":" + pay["method"]
    cohort_daily = pay.groupby(["cohort", "merchant_id", "day"]).agg(
        excess=("excess_fee", "sum"), n=("id", "count")
    ).reset_index()
    for cohort, grp in cohort_daily.groupby("cohort"):
        grp = grp.sort_values("day")
        positive_days = grp[grp["excess"] > 5]
        if len(positive_days) >= 3 and positive_days["excess"].mean() > 20:
            merchant_id = grp["merchant_id"].iloc[0]
            total_excess = positive_days["excess"].sum()
            confidence = min(0.95, 0.55 + 0.05 * len(positive_days))
            findings.append(_finding(
                merchant_id, "repeated_cohort_anomaly", "cohort", cohort, "cohort_rollup",
                confidence,
                evidence=[{
                    "type": "cohort", "id": cohort,
                    "summary": f"{len(positive_days)} days of elevated fees on cohort {cohort}",
                    "fields": {"days_affected": int(len(positive_days)),
                               "avg_daily_excess": round(float(positive_days["excess"].mean()), 2)},
                }],
                money_at_risk=total_excess, recoverable_amount=total_excess,
                breakdown=[{"component": "cumulative_cohort_fee_excess", "amount": round(float(total_excess), 2),
                            "source_type": "cohort", "source_id": cohort}],
                window_start=pd.Timestamp(grp["day"].min()), window_end=pd.Timestamp(grp["day"].max()),
            ))
    return findings


# ---------------------------------------------------------------------------
# 2. Delayed settlement
# ---------------------------------------------------------------------------
def detect_delayed_settlements(bundle):
    findings = []
    stl = bundle.settlements.copy()
    if stl.empty:
        return findings
    stl["delay_days"] = (stl["settled_at"] - stl["created_at"]).dt.total_seconds() / 86400.0
    flagged = stl[stl["delay_days"] >= T.DELAYED_SETTLEMENT_FLAG_DAYS]
    for _, row in flagged.iterrows():
        confidence = min(0.97, 0.65 + 0.06 * (row["delay_days"] - T.DELAYED_SETTLEMENT_FLAG_DAYS))
        findings.append(_finding(
            row["merchant_id"], "delayed_settlement", "settlement", row["id"], "settlement_delay_rule",
            confidence,
            evidence=[{
                "type": "settlement", "id": row["id"],
                "summary": f"Settled T+{row['delay_days']:.1f} vs T+{T.DELAYED_SETTLEMENT_BASELINE_DAYS} baseline",
                "fields": {"amount": row["amount"], "delay_days": round(row["delay_days"], 1),
                           "utr": row["utr"]},
            }],
            money_at_risk=row["amount"], recoverable_amount=0.0,
            breakdown=[{"component": "delayed_unsettled_amount", "amount": round(row["amount"], 2),
                        "source_type": "settlement", "source_id": row["id"]}],
            window_start=row["created_at"], window_end=row["settled_at"],
        ))
    return findings


# ---------------------------------------------------------------------------
# 3. Refund timing mismatch
# ---------------------------------------------------------------------------
def detect_refund_timing_mismatch(bundle):
    findings = []
    refunds = bundle.refunds.copy()
    items = bundle.settlement_items
    stl = bundle.settlements.set_index("id") if not bundle.settlements.empty else bundle.settlements
    if refunds.empty:
        return findings
    reflected_refund_ids = set(items.loc[items["refund_id"].notna(), "refund_id"]) if not items.empty else set()

    pay_settled_at = {}
    if not items.empty and not bundle.settlements.empty:
        pay_items = items[items["payment_id"].notna()].merge(
            bundle.settlements[["id", "settled_at"]], left_on="settlement_id", right_on="id",
            suffixes=("", "_stl"))
        pay_settled_at = pay_items.groupby("payment_id")["settled_at"].min().to_dict()

    for _, r in refunds.iterrows():
        if r["id"] in reflected_refund_ids:
            continue
        settled_at = pay_settled_at.get(r["payment_id"])
        if settled_at is None:
            continue
        if pd.isna(r["processed_at"]) or r["processed_at"] <= settled_at:
            continue
        confidence = 0.88
        findings.append(_finding(
            r["merchant_id"], "refund_timing_mismatch", "refund", r["id"], "refund_settlement_join",
            confidence,
            evidence=[{
                "type": "refund", "id": r["id"],
                "summary": f"Refund ₹{r['amount']:.2f} processed {r['processed_at']} — after "
                           f"related settlement closed {settled_at}",
                "fields": {"amount": r["amount"], "processed_at": str(r["processed_at"]),
                           "settlement_closed_at": str(settled_at)},
            }],
            money_at_risk=r["amount"], recoverable_amount=0.0,
            breakdown=[{"component": "unreflected_refund", "amount": round(r["amount"], 2),
                        "source_type": "refund", "source_id": r["id"]}],
            window_start=r["created_at"], window_end=r["processed_at"],
        ))
    return findings


# ---------------------------------------------------------------------------
# 4. Duplicate transaction
# ---------------------------------------------------------------------------
def detect_duplicate_transactions(bundle):
    """Same order captured more than once within a short window — the
    unambiguous signature of a duplicate charge (as opposed to two different
    orders that merely happen to share an amount)."""
    findings = []
    pay = bundle.payments.copy()
    if pay.empty:
        return findings
    seen = set()
    for order_id, grp in pay.groupby("order_id"):
        if len(grp) < 2:
            continue
        grp = grp.sort_values("created_at")
        times = grp["created_at"].tolist()
        ids = grp["id"].tolist()
        merchant_id = grp["merchant_id"].iloc[0]
        amount = grp["amount"].iloc[0]
        for i in range(1, len(times)):
            gap = (times[i] - times[i - 1]).total_seconds() / 60.0
            if gap <= T.DUPLICATE_WINDOW_MINUTES:
                dup_id = ids[i]
                if dup_id in seen:
                    continue
                seen.add(dup_id)
                dup_amount = grp["amount"].iloc[i]
                confidence = 0.92 if gap <= 5 else 0.8
                findings.append(_finding(
                    merchant_id, "duplicate_transaction", "payment", dup_id, "duplicate_window_rule",
                    confidence,
                    evidence=[{
                        "type": "payment", "id": dup_id,
                        "summary": f"₹{dup_amount:.2f} charged twice on order {order_id} within "
                                   f"{gap:.1f} min (orig payment {ids[i-1]})",
                        "fields": {"amount": dup_amount, "gap_minutes": round(gap, 1),
                                   "original_payment_id": ids[i - 1], "order_id": order_id},
                    }],
                    money_at_risk=dup_amount, recoverable_amount=dup_amount,
                    breakdown=[{"component": "duplicate_charge", "amount": round(float(dup_amount), 2),
                                "source_type": "payment", "source_id": dup_id}],
                    window_start=times[i - 1], window_end=times[i],
                ))
    return findings


# ---------------------------------------------------------------------------
# 5. Missing settlement item
# ---------------------------------------------------------------------------
def detect_missing_settlement_items(bundle):
    findings = []
    pay = bundle.payments.copy()
    items = bundle.settlement_items
    if pay.empty:
        return findings
    settled_payment_ids = set(items.loc[items["payment_id"].notna(), "payment_id"]) if not items.empty else set()
    cutoff = pay["created_at"].max() - timedelta(days=T.MISSING_SETTLEMENT_GRACE_DAYS)
    candidates = pay[(pay["status"] == "captured") & (pay["created_at"] <= cutoff)
                      & (~pay["id"].isin(settled_payment_ids))]
    for _, row in candidates.iterrows():
        expected_net = row["amount"] - row["fee"] - row["tax"]
        confidence = 0.9
        findings.append(_finding(
            row["merchant_id"], "missing_settlement_item", "payment", row["id"], "missing_item_rule",
            confidence,
            evidence=[{
                "type": "payment", "id": row["id"],
                "summary": f"Payment captured {row['created_at']} has no settlement item "
                           f"{T.MISSING_SETTLEMENT_GRACE_DAYS}+ days later",
                "fields": {"amount": row["amount"], "expected_net": round(expected_net, 2),
                           "captured_at": str(row["created_at"])},
            }],
            money_at_risk=expected_net, recoverable_amount=expected_net,
            breakdown=[{"component": "unsettled_payment_net", "amount": round(expected_net, 2),
                        "source_type": "payment", "source_id": row["id"]}],
            window_start=row["created_at"], window_end=row["created_at"],
        ))
    return findings


# ---------------------------------------------------------------------------
# 6. Partial settlement
# ---------------------------------------------------------------------------
def detect_partial_settlements(bundle):
    findings = []
    pay = bundle.payments.copy()
    items = bundle.settlement_items
    if pay.empty or items.empty:
        return findings
    pay_items = items[items["payment_id"].notna()].groupby("payment_id")["amount"].sum().rename("settled_net")
    merged = pay.join(pay_items, on="id")
    merged = merged[merged["settled_net"].notna()]
    merged["expected_net"] = merged["amount"] - merged["fee"] - merged["tax"]
    merged["shortfall"] = merged["expected_net"] - merged["settled_net"]
    merged["shortfall_ratio"] = merged["shortfall"] / merged["expected_net"].replace(0, np.nan)
    flagged = merged[(merged["shortfall"] > T.PARTIAL_SETTLEMENT_MIN_SHORTFALL)
                      & (merged["shortfall_ratio"] > T.PARTIAL_SETTLEMENT_MIN_RATIO)]
    for _, row in flagged.iterrows():
        confidence = min(0.95, 0.7 + min(row["shortfall_ratio"], 0.25))
        findings.append(_finding(
            row["merchant_id"], "partial_settlement", "payment", row["id"], "partial_settlement_rule",
            confidence,
            evidence=[{
                "type": "payment", "id": row["id"],
                "summary": f"Settled ₹{row['settled_net']:.2f} vs expected net ₹{row['expected_net']:.2f}",
                "fields": {"expected_net": round(row["expected_net"], 2),
                           "settled_net": round(row["settled_net"], 2),
                           "shortfall": round(row["shortfall"], 2)},
            }],
            money_at_risk=row["shortfall"], recoverable_amount=row["shortfall"],
            breakdown=[{"component": "settlement_shortfall", "amount": round(row["shortfall"], 2),
                        "source_type": "payment", "source_id": row["id"]}],
            window_start=row["created_at"], window_end=row["created_at"],
        ))
    return findings


# ---------------------------------------------------------------------------
# 7. Settlement variance (bank credit vs settlement amount)
# ---------------------------------------------------------------------------
def detect_settlement_variance(bundle):
    findings = []
    stl = bundle.settlements.copy()
    bank = bundle.bank_transactions
    if stl.empty or bank.empty:
        return findings
    bank_sum = bank.groupby("matched_settlement_id")["amount"].sum().rename("bank_amount")
    merged = stl.join(bank_sum, on="id")
    merged = merged[merged["bank_amount"].notna()]
    merged["variance"] = merged["amount"] - merged["bank_amount"]
    flagged = merged[(merged["variance"].abs() > T.SETTLEMENT_VARIANCE_MIN_ABS)
                      & ((merged["variance"].abs() / merged["amount"].replace(0, np.nan)) > T.SETTLEMENT_VARIANCE_MIN_RATIO)]
    for _, row in flagged.iterrows():
        confidence = 0.75
        findings.append(_finding(
            row["merchant_id"], "settlement_variance", "settlement", row["id"], "bank_settlement_join",
            confidence,
            evidence=[{
                "type": "settlement", "id": row["id"],
                "summary": f"Expected ₹{row['amount']:.2f}, bank credited ₹{row['bank_amount']:.2f}",
                "fields": {"expected": row["amount"], "received": row["bank_amount"],
                           "variance": round(row["variance"], 2)},
            }],
            money_at_risk=abs(row["variance"]), recoverable_amount=0.0,
            breakdown=[{"component": "unexplained_bank_variance", "amount": round(abs(row["variance"]), 2),
                        "source_type": "settlement", "source_id": row["id"]}],
            window_start=row["created_at"], window_end=row["settled_at"],
            extra={"expected": row["amount"], "received": row["bank_amount"]},
        ))
    return findings


# ---------------------------------------------------------------------------
# 8. Chargeback reserve
# ---------------------------------------------------------------------------
def detect_chargeback_reserve(bundle):
    findings = []
    disp = bundle.disputes
    if disp.empty:
        return findings
    open_disputes = disp[disp["status"].isin(["open", "reserve_held"])]
    for _, row in open_disputes.iterrows():
        confidence = 0.7 if row["status"] == "open" else 0.85
        findings.append(_finding(
            row["merchant_id"], "chargeback_reserve", "dispute", row["id"], "dispute_reserve_rule",
            confidence,
            evidence=[{
                "type": "dispute", "id": row["id"],
                "summary": f"Dispute {row['status']} for ₹{row['amount']:.2f} — reason: {row['reason']}",
                "fields": {"amount": row["amount"], "status": row["status"], "reason": row["reason"]},
            }],
            money_at_risk=row["amount"], recoverable_amount=0.0,
            breakdown=[{"component": "chargeback_reserve_held", "amount": round(row["amount"], 2),
                        "source_type": "dispute", "source_id": row["id"]}],
            window_start=row["created_at"], window_end=row["created_at"],
        ))
    return findings


# ---------------------------------------------------------------------------
# 9. Refund rate spike
# ---------------------------------------------------------------------------
def detect_refund_rate_spike(bundle):
    findings = []
    pay = bundle.payments.copy()
    refunds = bundle.refunds.copy()
    if pay.empty:
        return findings
    pay["day"] = pay["created_at"].dt.date
    refunds["day"] = refunds["created_at"].dt.date
    for merchant_id, pgrp in pay.groupby("merchant_id"):
        daily_pay = pgrp.groupby("day").agg(n=("id", "count"), amt=("amount", "sum"))
        rgrp = refunds[refunds["merchant_id"] == merchant_id]
        daily_refund = rgrp.groupby("day").agg(rn=("id", "count"), ramt=("amount", "sum"))
        daily = daily_pay.join(daily_refund, how="left").fillna(0)
        daily["rate"] = daily["rn"] / daily["n"].replace(0, np.nan)
        daily = daily.sort_index()
        if len(daily) < 14:
            continue
        baseline = daily["rate"].iloc[:-7].mean()
        recent = daily["rate"].iloc[-7:].mean()
        recent_volume = daily["n"].iloc[-7:].sum()
        std = daily["rate"].iloc[:-7].std(ddof=0) or 0.01
        z = (recent - baseline) / std
        if (baseline > 0 and recent / baseline >= T.REFUND_SPIKE_MIN_RATIO and z >= T.REFUND_SPIKE_MIN_Z
                and recent_volume >= T.REFUND_SPIKE_MIN_RECENT_VOLUME):
            recent_amt = daily["amt"].iloc[-7:].sum()
            incremental_exposure = max(0.0, (recent - baseline) * recent_amt)
            confidence = min(0.95, 0.6 + min(z / 20, 0.3))
            findings.append(_finding(
                merchant_id, "refund_rate_spike", "merchant", merchant_id, "refund_rate_ewma",
                confidence,
                evidence=[{
                    "type": "merchant_metric", "id": merchant_id,
                    "summary": f"7-day refund rate {recent:.1%} vs {baseline:.1%} baseline "
                               f"({recent/baseline:.1f}x, z={z:.1f})",
                    "fields": {"recent_rate": round(recent, 4), "baseline_rate": round(baseline, 4),
                               "z_score": round(float(z), 2)},
                }],
                money_at_risk=incremental_exposure, recoverable_amount=0.0,
                breakdown=[{"component": "incremental_refund_exposure", "amount": round(incremental_exposure, 2),
                            "source_type": "merchant", "source_id": merchant_id}],
                window_start=pd.Timestamp(daily.index[-7]), window_end=pd.Timestamp(daily.index[-1]),
            ))
    return findings


# ---------------------------------------------------------------------------
# 10. Settlement degradation (day-over-day trend)
# ---------------------------------------------------------------------------
def detect_settlement_degradation(bundle):
    findings = []
    stl = bundle.settlements.copy()
    if stl.empty:
        return findings
    stl["delay_days"] = (stl["settled_at"] - stl["created_at"]).dt.total_seconds() / 86400.0
    stl["day"] = stl["created_at"].dt.date
    for merchant_id, grp in stl.groupby("merchant_id"):
        daily = grp.groupby("day")["delay_days"].mean().sort_index()
        if len(daily) < T.DEGRADATION_MIN_WINDOW:
            continue
        recent = daily.iloc[-T.DEGRADATION_MIN_WINDOW:]
        x = np.arange(len(recent))
        slope, intercept = np.polyfit(x, recent.values, 1)
        if slope >= T.DEGRADATION_MIN_SLOPE_DAYS:
            recent_amount = grp[grp["day"].isin(recent.index)]["amount"].sum()
            projected_delay = intercept + slope * (len(recent) + 20)
            projected_exposure = recent_amount * (projected_delay / max(recent.values[-1], 1))
            confidence = min(0.92, 0.55 + slope * 0.5)
            findings.append(_finding(
                merchant_id, "settlement_degradation", "merchant", merchant_id, "delay_trend_slope",
                confidence,
                evidence=[{
                    "type": "merchant_metric", "id": merchant_id,
                    "summary": f"Settlement delay trending up {slope:.2f} days/day over last "
                               f"{T.DEGRADATION_MIN_WINDOW} days",
                    "fields": {"slope_days_per_day": round(float(slope), 3),
                               "latest_delay_days": round(float(recent.values[-1]), 2)},
                }],
                money_at_risk=recent_amount, recoverable_amount=0.0,
                breakdown=[{"component": "at_risk_settlement_volume", "amount": round(float(recent_amount), 2),
                            "source_type": "merchant", "source_id": merchant_id}],
                window_start=pd.Timestamp(recent.index[0]), window_end=pd.Timestamp(recent.index[-1]),
                extra={"projected_month_end_exposure": round(float(projected_exposure), 2)},
            ))
    return findings


# ---------------------------------------------------------------------------
# 11. Merchant-level anomaly
#
# Two implementations of the SAME exception type, kept side by side on
# purpose (see app/ml/anomaly_model.py module docstring for the full
# reasoning and app/services/train_ml_model.py for the measured comparison):
#
#   detect_merchant_level_anomalies_statistical — the original hand-written
#     heuristic (ticket-size + refund-rate z-scores only). Kept as the
#     always-available fallback and as the "existing statistical detector"
#     baseline in the model comparison. Its detector name was previously
#     the misleading "isolation_style_zscore" — it never used
#     IsolationForest; that has been corrected here.
#
#   detect_merchant_level_anomalies_ml — a genuinely trained
#     sklearn.ensemble.IsolationForest over 13 engineered merchant-day
#     features (app/analytics/features.py), loaded from the artifact
#     app/services/train_ml_model.py produces. Falls back to nothing (not
#     to the heuristic) if no model has been trained yet, so its absence is
#     visible rather than silently masked.
#
#   detect_merchant_level_anomalies_ensemble — the function actually
#     registered in ALL_DETECTORS below. A safe OR-ensemble: a merchant is
#     flagged if EITHER the statistical heuristic OR the ML model flags it,
#     each still producing its own independent Finding with its own
#     detector name and evidence — the ensemble does not average away which
#     signal actually fired. This choice (rather than ML-only or rules-only)
#     is the one the measured comparison in
#     data/benchmarks/ml_comparison.json actually supports; see claude.md.
# ---------------------------------------------------------------------------
def detect_merchant_level_anomalies_statistical(bundle):
    findings = []
    pay = bundle.payments.copy()
    refunds = bundle.refunds.copy()
    if pay.empty:
        return findings
    pay["day"] = pay["created_at"].dt.date
    refunds["day"] = refunds["created_at"].dt.date

    daily = pay.groupby(["merchant_id", "day"]).agg(
        avg_ticket=("amount", "mean"), n_pay=("id", "count"),
        fee_excess=("fee", lambda s: (s - pay.loc[s.index, "expected_fee"]).sum()),
        total_amt=("amount", "sum"),
    ).reset_index()
    rdaily = refunds.groupby(["merchant_id", "day"]).agg(n_refund=("id", "count")).reset_index()
    daily = daily.merge(rdaily, on=["merchant_id", "day"], how="left").fillna({"n_refund": 0})
    daily["refund_rate"] = daily["n_refund"] / daily["n_pay"].replace(0, np.nan)

    for merchant_id, grp in daily.groupby("merchant_id"):
        if len(grp) < 15:
            continue
        grp = grp.copy()
        grp["z_ticket"] = (grp["avg_ticket"] - grp["avg_ticket"].mean()) / (grp["avg_ticket"].std(ddof=0) or 1)
        grp["z_refund"] = (grp["refund_rate"] - grp["refund_rate"].mean()) / (grp["refund_rate"].std(ddof=0) or 1)
        grp["anomaly_score"] = (grp["z_ticket"].clip(lower=0) + grp["z_refund"].clip(lower=0)) / 6.0
        recent = grp.sort_values("day").iloc[-10:]
        flagged_days = recent[recent["anomaly_score"] > T.MERCHANT_ANOMALY_MIN_SCORE]
        if len(flagged_days) >= 4:
            total_amt = flagged_days["total_amt"].sum()
            confidence = min(0.9, 0.5 + 0.08 * len(flagged_days))
            findings.append(_finding(
                merchant_id, "merchant_level_anomaly", "merchant", merchant_id, "merchant_zscore_heuristic",
                confidence,
                evidence=[{
                    "type": "merchant_metric", "id": merchant_id,
                    "summary": f"{len(flagged_days)} of last 10 days show elevated ticket size + "
                               f"refund rate together",
                    "fields": {"days_flagged": int(len(flagged_days)),
                               "avg_anomaly_score": round(float(flagged_days['anomaly_score'].mean()), 3)},
                }],
                money_at_risk=total_amt * T.MERCHANT_ANOMALY_RISK_SHARE, recoverable_amount=0.0,
                breakdown=[{"component": "at_risk_share_of_volume",
                            "amount": round(float(total_amt * T.MERCHANT_ANOMALY_RISK_SHARE), 2),
                            "source_type": "merchant", "source_id": merchant_id}],
                window_start=pd.Timestamp(recent["day"].min()), window_end=pd.Timestamp(recent["day"].max()),
            ))
    return findings


def detect_merchant_level_anomalies_ml(bundle):
    """Real Isolation Forest inference — see app/ml/anomaly_model.py. Returns
    no findings (not an error) if no model has been trained yet; run
    `python -m app.services.train_ml_model` or `python -m app.services.seed`
    first."""
    findings = []
    from app.ml import anomaly_model as ml

    loaded = ml.load()
    if loaded is None:
        return findings
    model, scaler, meta = loaded

    features = build_merchant_day_features(bundle)
    if features.empty:
        return findings
    _train_df, score_df, _cutoff = ml.time_split(features, meta["score_window_days"])
    if score_df.empty:
        return findings
    score_df = score_df.copy()
    score_df["anomaly_score"] = ml.score_dataframe(score_df, model, scaler)
    threshold = meta["threshold"]

    for merchant_id, grp in score_df.groupby("merchant_id"):
        flagged = grp[grp["anomaly_score"] >= threshold]
        if flagged.empty:
            continue
        worst = flagged.loc[flagged["anomaly_score"].idxmax()]
        contributions = ml.top_feature_contributions(worst, meta)
        total_amt = flagged["total_amount"].sum()
        confidence = ml.score_to_confidence(float(worst["anomaly_score"]), meta)
        top_names = ", ".join(c["feature"] for c in contributions) or "no dominant single feature"
        findings.append(_finding(
            merchant_id, "merchant_level_anomaly", "merchant", merchant_id, "isolation_forest",
            confidence,
            evidence=[{
                "type": "merchant_metric", "id": merchant_id,
                "summary": f"Isolation Forest flagged {len(flagged)} of last {meta['score_window_days']} days "
                           f"(peak anomaly score {worst['anomaly_score']:.3f} vs threshold {threshold:.3f} "
                           f"on {pd.Timestamp(worst['day']).date()}); top signals: {top_names}",
                "fields": {
                    "days_flagged": int(len(flagged)),
                    "peak_anomaly_score": round(float(worst["anomaly_score"]), 4),
                    "threshold": round(float(threshold), 4),
                    "top_contributions": contributions,
                },
            }],
            money_at_risk=total_amt * T.MERCHANT_ANOMALY_RISK_SHARE, recoverable_amount=0.0,
            breakdown=[{"component": "at_risk_share_of_volume",
                        "amount": round(float(total_amt * T.MERCHANT_ANOMALY_RISK_SHARE), 2),
                        "source_type": "merchant", "source_id": merchant_id}],
            window_start=pd.Timestamp(flagged["day"].min()), window_end=pd.Timestamp(flagged["day"].max()),
            extra={"model": "isolation_forest", "model_trained_at": meta.get("trained_at")},
        ))
    return findings


def detect_merchant_level_anomalies_ensemble(bundle):
    """OR-ensemble keyed by merchant_id: a merchant flagged by either signal
    produces exactly one Finding for this exception type (never two), so
    money_at_risk is never double-counted for the same merchant window (see
    claude.md "Why detection engines never double-count money"). When both
    signals agree, the statistical finding is kept (money_at_risk stays
    exact/simple arithmetic) but the ML evidence is folded in alongside it
    so the agreement itself is visible rather than the ML signal being
    silently dropped."""
    statistical = detect_merchant_level_anomalies_statistical(bundle)
    ml_findings = {f["merchant_id"]: f for f in detect_merchant_level_anomalies_ml(bundle)}
    combined = []
    for f in statistical:
        mid = f["merchant_id"]
        if mid in ml_findings:
            f = dict(f)
            f["evidence"] = f["evidence"] + ml_findings[mid]["evidence"]
            f["detector"] = f["detector"] + "+isolation_forest_agreement"
            del ml_findings[mid]
        combined.append(f)
    combined.extend(ml_findings.values())
    return combined


ALL_DETECTORS = [
    detect_fee_anomalies,
    detect_delayed_settlements,
    detect_refund_timing_mismatch,
    detect_duplicate_transactions,
    detect_missing_settlement_items,
    detect_partial_settlements,
    detect_settlement_variance,
    detect_chargeback_reserve,
    detect_refund_rate_spike,
    detect_settlement_degradation,
    detect_merchant_level_anomalies_ensemble,
]


def run_all_detectors(bundle):
    findings = []
    for fn in ALL_DETECTORS:
        findings.extend(fn(bundle))
    return findings
