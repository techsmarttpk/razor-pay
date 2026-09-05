"""Synthetic Razorpay-style merchant financial dataset generator.

Generates a realistic multi-entity dataset (merchants, customers, orders,
payments, refunds, settlements, settlement items, disputes, fees, bank
transactions, ledger entries) with 16 deliberately injected scenarios and a
ground-truth label for every injected anomaly. Ground truth is split into
`calibration` (used to pick detector thresholds) and `holdout` (used only for
evaluation) so the benchmark in app/services/evaluation.py is not evaluating
on data it was tuned against.

Nothing here is consumed by the detection engines at inference time except
the raw financial entities themselves — ground truth is for evaluation only.
"""
import random
import uuid
from datetime import datetime, timedelta

import numpy as np

SCENARIOS = [
    "normal_exact_match",
    "batched_settlement",
    "delayed_settlement",
    "refund_timing_mismatch",
    "duplicate_transaction",
    "missing_settlement_item",
    "fee_anomaly",
    "partial_settlement",
    "settlement_variance",
    "chargeback_reserve",
    "repeated_cohort_anomaly",
    "refund_rate_spike",
    "merchant_level_anomaly",
    "settlement_degradation",
    "unresolved_exception",
    "false_positive_benign",
]

METHODS = ["card", "upi", "netbanking", "wallet"]
METHOD_WEIGHTS = [0.45, 0.38, 0.12, 0.05]

MERCHANT_CATEGORIES = [
    "e-commerce", "food_delivery", "travel", "saas", "education",
    "healthcare", "gaming", "utilities", "logistics", "retail",
]


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class IdGen:
    """Deterministic id counter — cheap and stable across runs for a given seed."""
    def __init__(self):
        self.counters = {}

    def next(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}_{self.counters[prefix]:07d}"


class Generator:
    def __init__(self, seed: int = 42, n_merchants: int = 42, sim_days: int = 60,
                 target_payments: int = 9000):
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.seed = seed
        self.n_merchants = n_merchants
        self.sim_days = sim_days
        self.target_payments = target_payments
        self.today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        self.start_day = self.today - timedelta(days=sim_days)
        self.ids = IdGen()

        self.merchants = []
        self.customers = []
        self.orders = []
        self.payments = []
        self.refunds = []
        self.settlements = []
        self.settlement_items = []
        self.disputes = []
        self.fees = []
        self.bank_transactions = []
        self.ledger_entries = []
        self.labels = []

        # scenario assignment: pick merchants to carry each "merchant-level"
        # scenario, and separately inject "instance-level" scenarios
        # (duplicate, fee anomaly, etc.) scattered across many merchants.
        self._scenario_merchants = {}

    # ------------------------------------------------------------------
    # Entity bootstrap
    # ------------------------------------------------------------------
    def gen_merchants(self):
        for i in range(self.n_merchants):
            tier = self.rng.choices(["small", "medium", "large"], weights=[0.5, 0.35, 0.15])[0]
            daily_volume = {"small": (2, 12), "medium": (12, 45), "large": (45, 140)}[tier]
            m = {
                "id": self.ids.next("mer"),
                "name": f"{self.rng.choice(['Nova', 'Zen', 'Kite', 'Orbit', 'Swift', 'Metro', 'Bloom', 'Pulse', 'Vertex', 'Anchor'])} "
                        f"{self.rng.choice(['Retail', 'Mart', 'Foods', 'Travels', 'Labs', 'Works', 'Bazaar', 'Studio'])}",
                "category": self.rng.choice(MERCHANT_CATEGORIES),
                "risk_tier": tier,
                "mdr_rate": round(self.rng.uniform(0.015, 0.025), 4),
                "onboarded_at": self.start_day - timedelta(days=self.rng.randint(30, 900)),
                "_daily_volume_range": daily_volume,
                "_tier": tier,
            }
            self.merchants.append(m)

        # assign scenario carriers: each merchant-level/day-level scenario gets
        # a handful of dedicated merchants so effects are attributable and
        # evaluable without contaminating every merchant at once.
        pool = [m["id"] for m in self.merchants]
        self.rng.shuffle(pool)
        cursor = 0
        merchant_level_scenarios = [
            "merchant_level_anomaly", "settlement_degradation", "refund_rate_spike",
            "repeated_cohort_anomaly", "unresolved_exception",
        ]
        for sc in merchant_level_scenarios:
            n = 6 if sc != "unresolved_exception" else 4
            self._scenario_merchants[sc] = pool[cursor:cursor + n]
            cursor += n
        # remaining merchants are available for scattered instance-level injections
        self._scattered_pool = pool[cursor:] or pool

    def gen_customers(self):
        for m in self.merchants:
            n = {"small": 30, "medium": 90, "large": 260}[m["_tier"]]
            for _ in range(n):
                self.customers.append({
                    "id": self.ids.next("cus"),
                    "merchant_id": m["id"],
                    "name": f"Customer {self.rng.randint(10000, 99999)}",
                    "email": f"user{self.rng.randint(10000,99999)}@example.com",
                })
        self._customers_by_merchant = {}
        for c in self.customers:
            self._customers_by_merchant.setdefault(c["merchant_id"], []).append(c)

    # ------------------------------------------------------------------
    # Daily transaction simulation
    # ------------------------------------------------------------------
    def _amount_for(self, category: str) -> float:
        base = {
            "e-commerce": 1200, "food_delivery": 420, "travel": 6500, "saas": 2400,
            "education": 3200, "healthcare": 1800, "gaming": 350, "utilities": 950,
            "logistics": 1500, "retail": 900,
        }.get(category, 1000)
        val = self.np_rng.lognormal(mean=np.log(base), sigma=0.6)
        return round(float(max(50, min(val, base * 25))), 2)

    def simulate(self):
        total_target = self.target_payments
        n_days = self.sim_days
        # degradation schedule for settlement_degradation merchants: settlement
        # delay grows day by day over the final 10 days of the window
        degradation_merchants = set(self._scenario_merchants.get("settlement_degradation", []))
        refund_spike_merchants = set(self._scenario_merchants.get("refund_rate_spike", []))
        cohort_repeat_merchants = set(self._scenario_merchants.get("repeated_cohort_anomaly", []))
        merchant_level_anom = set(self._scenario_merchants.get("merchant_level_anomaly", []))
        unresolved_merchants = set(self._scenario_merchants.get("unresolved_exception", []))

        # expected raw daily total if we used the tier ranges as-is, so we
        # can scale uniformly to land near target_payments regardless of
        # n_merchants/sim_days choices
        expected_raw_daily = sum((lo + hi) / 2 for lo, hi in
                                  (m["_daily_volume_range"] for m in self.merchants))
        expected_raw_total = expected_raw_daily * n_days
        scale = total_target / expected_raw_total if expected_raw_total else 1.0

        for day_offset in range(n_days):
            day = self.start_day + timedelta(days=day_offset)
            for m in self.merchants:
                lo, hi = m["_daily_volume_range"]
                base_n = self.rng.randint(lo, hi)
                n = max(1, round(base_n * scale))
                is_last10 = day_offset >= n_days - 10
                degrade_factor = 0
                if m["id"] in degradation_merchants and is_last10:
                    degrade_factor = day_offset - (n_days - 10) + 1  # 1..10

                refund_rate = 0.03
                if m["id"] in refund_spike_merchants and is_last10:
                    refund_rate = 0.03 + 0.05 * (day_offset - (n_days - 10) + 1)

                fee_bias = 0.0
                if m["id"] in cohort_repeat_merchants:
                    fee_bias = 0.006  # persistent small fee overcharge on a cohort

                merchant_wide_bias = m["id"] in merchant_level_anom and is_last10

                self._simulate_merchant_day(
                    m, day, n, degrade_factor, refund_rate, fee_bias,
                    merchant_wide_bias, m["id"] in unresolved_merchants and is_last10,
                )

    def _simulate_merchant_day(self, m, day, n, degrade_factor, refund_rate,
                                fee_bias, merchant_wide_bias, unresolved_day):
        customers = self._customers_by_merchant.get(m["id"], [])
        if not customers:
            return
        day_payments = []
        for _ in range(n):
            c = self.rng.choice(customers)
            amount = self._amount_for(m["category"])
            if merchant_wide_bias:
                amount *= self.rng.uniform(1.15, 1.4)  # elevated ticket sizes, part of merchant-wide anomaly

            created_at = day + timedelta(
                hours=self.rng.randint(6, 22), minutes=self.rng.randint(0, 59)
            )
            order = {
                "id": self.ids.next("order"),
                "merchant_id": m["id"],
                "customer_id": c["id"],
                "amount": amount,
                "currency": "INR",
                "status": "paid",
                "created_at": created_at,
            }
            self.orders.append(order)

            method = self.rng.choices(METHODS, weights=METHOD_WEIGHTS)[0]
            expected_fee = round(amount * m["mdr_rate"], 2)
            actual_fee = expected_fee
            cohort = f"{m['id']}:{method}:{day.strftime('%Y-%m-%d')}"

            payment = {
                "id": self.ids.next("pay"),
                "order_id": order["id"],
                "merchant_id": m["id"],
                "amount": amount,
                "method": method,
                "status": "captured",
                "fee": actual_fee,
                "expected_fee": expected_fee,
                "tax": round(actual_fee * 0.18, 2),
                "cohort": cohort,
                "created_at": created_at,
                "captured_at": created_at + timedelta(minutes=self.rng.randint(0, 3)),
                "_scenario": None,
                "_settlement_delay_days": 2 + (degrade_factor if degrade_factor else 0),
            }
            day_payments.append(payment)
            self.payments.append(payment)

        self._inject_instance_scenarios(m, day, day_payments, fee_bias)
        self._simulate_refunds(m, day_payments, refund_rate)
        self._settle_day(m, day, day_payments, unresolved_day)

    # ------------------------------------------------------------------
    # Scenario injection (instance-level, scattered across many merchants)
    # ------------------------------------------------------------------
    def _label(self, merchant_id, scenario_type, entity_type, entity_id,
               expected_amount, is_true_anomaly=True, description="", force_split=None):
        split = force_split or ("calibration" if self.rng.random() < 0.7 else "holdout")
        self.labels.append({
            "id": self.ids.next("lbl"),
            "merchant_id": merchant_id,
            "scenario_type": scenario_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "expected_amount": round(expected_amount, 2),
            "is_true_anomaly": is_true_anomaly,
            "split": split,
            "injected_at": datetime.utcnow(),
            "description": description,
        })

    def _inject_instance_scenarios(self, m, day, day_payments, fee_bias):
        if not day_payments:
            return

        # fee anomaly: ~1.5% of payments get an inflated actual fee
        for p in day_payments:
            if self.rng.random() < 0.015:
                bump = self.rng.uniform(0.008, 0.03)
                p["fee"] = round(p["fee"] + p["amount"] * bump, 2)
                p["tax"] = round(p["fee"] * 0.18, 2)
                self._label(m["id"], "fee_anomaly", "payment", p["id"],
                            expected_amount=p["fee"] - p["expected_fee"],
                            description="Actual fee charged above merchant MDR baseline")

        if fee_bias:
            # persistent cohort-level overcharge (repeated_cohort_anomaly) —
            # ground truth label is emitted once per merchant in
            # gen_merchant_level_labels(), matching the detector's cohort key
            cohort_targets = [p for p in day_payments if p["method"] == "upi"]
            for p in cohort_targets:
                p["fee"] = round(p["fee"] + p["amount"] * fee_bias, 2)
                p["tax"] = round(p["fee"] * 0.18, 2)

        # duplicate transaction: ~0.8% chance a payment gets an accidental duplicate
        for p in list(day_payments):
            if self.rng.random() < 0.008:
                dup = dict(p)
                dup["id"] = self.ids.next("pay")
                dup["created_at"] = p["created_at"] + timedelta(minutes=self.rng.randint(1, 4))
                dup["captured_at"] = dup["created_at"]
                dup["_settlement_delay_days"] = p["_settlement_delay_days"]
                self.payments.append(dup)
                day_payments.append(dup)
                self._label(m["id"], "duplicate_transaction", "payment", dup["id"],
                            expected_amount=dup["amount"],
                            description=f"Duplicate of payment {p['id']} within minutes")

        # false positive benign: legitimately large ticket, fully reconciled,
        # should NOT be flagged as high severity by a well-tuned detector
        if self.rng.random() < 0.01 and day_payments:
            p = self.rng.choice(day_payments)
            p["amount"] = round(p["amount"] * self.rng.uniform(4, 7), 2)
            p["fee"] = round(p["amount"] * m["mdr_rate"], 2)
            p["expected_fee"] = p["fee"]
            p["tax"] = round(p["fee"] * 0.18, 2)
            self._label(m["id"], "false_positive_benign", "payment", p["id"],
                        expected_amount=0.0, is_true_anomaly=False,
                        description="Large but fully explained/reconciled order — should not escalate")

    def _simulate_refunds(self, m, day_payments, refund_rate):
        for p in day_payments:
            if self.rng.random() < refund_rate:
                full = self.rng.random() < 0.75
                amount = p["amount"] if full else round(p["amount"] * self.rng.uniform(0.2, 0.8), 2)
                created = p["captured_at"] + timedelta(hours=self.rng.randint(1, 96))
                speed = self.rng.choices(["instant", "normal"], weights=[0.3, 0.7])[0]
                processed_delay = timedelta(minutes=30) if speed == "instant" else timedelta(days=self.rng.randint(1, 5))
                refund = {
                    "id": self.ids.next("rfnd"),
                    "payment_id": p["id"],
                    "merchant_id": m["id"],
                    "amount": amount,
                    "status": "processed",
                    "reason": self.rng.choice(["customer_request", "order_cancelled", "product_issue", "duplicate_charge"]),
                    "created_at": created,
                    "processed_at": created + processed_delay,
                    "speed": speed,
                    "_mismatch": False,
                }
                # refund timing mismatch: settlement adjustment lags behind
                # the refund itself, so settlement variance shows up before
                # the refund is reflected — ~12% of refunds carry this
                if self.rng.random() < 0.12:
                    refund["_mismatch"] = True
                    refund["processed_at"] = refund["processed_at"] + timedelta(days=self.rng.randint(3, 8))
                    self._label(m["id"], "refund_timing_mismatch", "refund", refund["id"],
                                expected_amount=amount,
                                description="Refund processed but settlement adjustment lagged")
                self.refunds.append(refund)

    # ------------------------------------------------------------------
    # Settlement + downstream entities
    # ------------------------------------------------------------------
    def _settle_day(self, m, day, day_payments, unresolved_day):
        if not day_payments:
            return
        refunds_by_payment = {}
        for r in self.refunds:
            refunds_by_payment.setdefault(r["payment_id"], []).append(r)

        # group payments into batches of ~8-20 -> "batched settlement" is just
        # normal multi-payment settlement behaviour
        batch_size = self.rng.randint(8, 20)
        batches = [day_payments[i:i + batch_size] for i in range(0, len(day_payments), batch_size)]

        for batch in batches:
            delay_days = batch[0]["_settlement_delay_days"]
            settled_at = batch[0]["captured_at"] + timedelta(days=delay_days, hours=self.rng.randint(0, 6))
            settlement_amount = 0.0
            items = []
            missing_item_payment = None
            partial_item_payment = None

            if self.rng.random() < 0.01:
                missing_item_payment = self.rng.choice(batch)
            if self.rng.random() < 0.012:
                candidates = [p for p in batch if p is not missing_item_payment]
                if candidates:
                    partial_item_payment = self.rng.choice(candidates)

            settlement_id = self.ids.next("stl")
            for p in batch:
                if p is missing_item_payment:
                    self._label(m["id"], "missing_settlement_item", "payment", p["id"],
                                expected_amount=p["amount"] - p["fee"] - p["tax"],
                                description="Captured payment never received a settlement item")
                    continue  # money not settled at all — the anomaly

                net = round(p["amount"] - p["fee"] - p["tax"], 2)
                if p is partial_item_payment:
                    shortfall = round(net * self.rng.uniform(0.15, 0.4), 2)
                    net = round(net - shortfall, 2)
                    self._label(m["id"], "partial_settlement", "payment", p["id"],
                                expected_amount=shortfall,
                                description="Settlement item amount short of expected net payout")

                items.append({
                    "id": self.ids.next("sti"),
                    "settlement_id": settlement_id,
                    "payment_id": p["id"],
                    "refund_id": None,
                    "amount": net,
                    "item_type": "payment",
                })
                settlement_amount += net

                for r in refunds_by_payment.get(p["id"], []):
                    if r["_mismatch"] and r["processed_at"] > settled_at:
                        continue  # deliberately NOT reflected yet -> variance
                    items.append({
                        "id": self.ids.next("sti"),
                        "settlement_id": settlement_id,
                        "payment_id": None,
                        "refund_id": r["id"],
                        "amount": -r["amount"],
                        "item_type": "refund",
                    })
                    settlement_amount -= r["amount"]

            if not items and settlement_amount == 0:
                continue

            # delayed settlement scenario: mark separately for evaluation when
            # the delay is materially beyond the T+2 baseline
            if delay_days >= 4:
                self._label(m["id"], "delayed_settlement", "settlement", settlement_id,
                            expected_amount=round(settlement_amount, 2),
                            description=f"Settlement delayed T+{delay_days} vs T+2 baseline")

            settlement = {
                "id": settlement_id,
                "merchant_id": m["id"],
                "utr": f"UTR{self.rng.randint(10**9, 10**10-1)}",
                "amount": round(settlement_amount, 2),
                "status": "processed",
                "created_at": batch[0]["captured_at"],
                "settled_at": settled_at,
            }
            self.settlements.append(settlement)
            self.settlement_items.extend(items)

            bank_amount = settlement["amount"]
            if unresolved_day and self.rng.random() < 0.3:
                # residual, deliberately unexplained variance that no single
                # hypothesis fully accounts for
                residual = round(settlement["amount"] * self.rng.uniform(0.01, 0.025), 2)
                bank_amount = round(settlement["amount"] - residual, 2)
                self._label(m["id"], "unresolved_exception", "settlement", settlement_id,
                            expected_amount=residual,
                            description="Residual settlement variance with no single confirmed cause")
            elif self.rng.random() < 0.01:
                # generic settlement_variance: small unexplained shortfall
                residual = round(settlement["amount"] * self.rng.uniform(0.005, 0.015), 2)
                bank_amount = round(settlement["amount"] - residual, 2)
                self._label(m["id"], "settlement_variance", "settlement", settlement_id,
                            expected_amount=residual,
                            description="Bank credit short of expected settlement amount")

            self.bank_transactions.append({
                "id": self.ids.next("bnk"),
                "merchant_id": m["id"],
                "amount": bank_amount,
                "utr": settlement["utr"],
                "value_date": settled_at,
                "matched_settlement_id": settlement_id,
            })

            self.ledger_entries.append({
                "id": self.ids.next("led"),
                "merchant_id": m["id"],
                "account": "bank",
                "debit": bank_amount,
                "credit": 0.0,
                "ref_type": "settlement",
                "ref_id": settlement_id,
                "created_at": settled_at,
            })
            self.ledger_entries.append({
                "id": self.ids.next("led"),
                "merchant_id": m["id"],
                "account": "sales",
                "debit": 0.0,
                "credit": bank_amount,
                "ref_type": "settlement",
                "ref_id": settlement_id,
                "created_at": settled_at,
            })

        self._maybe_dispute(m, day_payments)

    def _maybe_dispute(self, m, day_payments):
        for p in day_payments:
            if self.rng.random() < 0.004:
                created = p["captured_at"] + timedelta(days=self.rng.randint(2, 20))
                reserve_amount = round(p["amount"], 2)
                status = self.rng.choices(["open", "reserve_held", "won", "lost"],
                                           weights=[0.35, 0.3, 0.2, 0.15])[0]
                dispute = {
                    "id": self.ids.next("disp"),
                    "payment_id": p["id"],
                    "merchant_id": m["id"],
                    "amount": reserve_amount,
                    "status": status,
                    "reason": self.rng.choice(["fraud_claim", "goods_not_received", "unrecognized_charge"]),
                    "created_at": created,
                    "resolved_at": created + timedelta(days=self.rng.randint(5, 30)) if status in ("won", "lost") else None,
                }
                self.disputes.append(dispute)
                if status in ("open", "reserve_held"):
                    self._label(m["id"], "chargeback_reserve", "dispute", dispute["id"],
                                expected_amount=reserve_amount,
                                description="Dispute reserve held pending resolution")

    def gen_merchant_level_labels(self):
        """Merchant-level scenarios (refund_rate_spike, settlement_degradation,
        merchant_level_anomaly) are persistent conditions over a window, not a
        single entity — one label per affected merchant. expected_amount is
        left at 0 (aggregate scenario; detection presence, not amount
        accuracy, is what's evaluated for these)."""
        # split is forced to alternate rather than drawn randomly: with only
        # a handful of carrier merchants per scenario, a random 70/30 draw
        # can easily land 0 in holdout by chance, leaving that scenario
        # unevaluated. Alternating guarantees every scenario type is
        # actually scored on held-out data.
        for scenario in ("refund_rate_spike", "settlement_degradation", "merchant_level_anomaly"):
            for i, merchant_id in enumerate(self._scenario_merchants.get(scenario, [])):
                split = "holdout" if i % 3 == 0 else "calibration"
                self._label(merchant_id, scenario, "merchant", merchant_id,
                            expected_amount=0.0,
                            description=f"Merchant-level {scenario} over final 10 days of window",
                            force_split=split)

        # repeated_cohort_anomaly: one label per merchant, entity_id matches
        # the detector's cohort key ("<merchant_id>:<method>") since the
        # excess is spread across every day, not a single day's payments
        by_merchant_upi_excess = {}
        for p in self.payments:
            if p["method"] != "upi":
                continue
            by_merchant_upi_excess.setdefault(p["merchant_id"], []).append(p)
        for i, merchant_id in enumerate(self._scenario_merchants.get("repeated_cohort_anomaly", [])):
            excess = sum(p["amount"] * 0.006 for p in by_merchant_upi_excess.get(merchant_id, []))
            if excess > 0:
                split = "holdout" if i % 3 == 0 else "calibration"
                self._label(merchant_id, "repeated_cohort_anomaly", "cohort",
                            f"{merchant_id}:upi", expected_amount=excess,
                            description="Recurring fee overcharge on UPI cohort across the window",
                            force_split=split)

    def gen_fees_table(self):
        for p in self.payments:
            self.fees.append({
                "id": self.ids.next("fee"),
                "payment_id": p["id"],
                "merchant_id": p["merchant_id"],
                "expected_fee": p["expected_fee"],
                "actual_fee": p["fee"],
                "fee_type": "mdr",
            })

    def gen_normal_labels(self):
        # sample a set of untouched payments as explicit "normal_exact_match"
        # negatives so precision/recall has a real negative population
        anomalous_ids = {l["entity_id"] for l in self.labels}
        candidates = [p for p in self.payments if p["id"] not in anomalous_ids]
        sample = self.rng.sample(candidates, min(400, len(candidates)))
        for p in sample:
            self._label(p["merchant_id"], "normal_exact_match", "payment", p["id"],
                        expected_amount=0.0, is_true_anomaly=False,
                        description="Fully reconciled, on-time, at-baseline transaction")

    def run(self):
        self.gen_merchants()
        self.gen_customers()
        self.simulate()
        self.gen_merchant_level_labels()
        self.gen_fees_table()
        self.gen_normal_labels()
        return self


def generate_dataset(seed: int = 42, n_merchants: int = 42, sim_days: int = 60,
                      target_payments: int = 9000) -> Generator:
    gen = Generator(seed=seed, n_merchants=n_merchants, sim_days=sim_days,
                     target_payments=target_payments)
    gen.run()
    return gen
