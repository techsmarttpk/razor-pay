"""Seed command: generate synthetic dataset, load into SQLite, export CSVs,
run detection once, and produce the evaluation benchmark. This is the single
command a fresh session/demo needs to run.

Usage:
    python -m app.services.seed
"""
import json
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core.db import Base, engine, SessionLocal, DATA_DIR  # noqa: E402
from app.models import orm  # noqa: E402
from app.services.data_generator import generate_dataset  # noqa: E402


TABLE_MODEL_MAP = [
    ("merchants", orm.Merchant, ["merchants"]),
    ("customers", orm.Customer, ["customers"]),
    ("orders", orm.Order, ["orders"]),
    ("payments", orm.Payment, ["payments"]),
    ("refunds", orm.Refund, ["refunds"]),
    ("settlements", orm.Settlement, ["settlements"]),
    ("settlement_items", orm.SettlementItem, ["settlement_items"]),
    ("disputes", orm.Dispute, ["disputes"]),
    ("fees", orm.Fee, ["fees"]),
    ("bank_transactions", orm.BankTransaction, ["bank_transactions"]),
    ("ledger_entries", orm.LedgerEntry, ["ledger_entries"]),
    ("labels", orm.AnomalyLabel, ["anomaly_labels"]),
]

INTERNAL_ONLY_FIELDS = {"_daily_volume_range", "_tier", "_scenario",
                        "_settlement_delay_days", "_mismatch"}


def _clean(rows):
    out = []
    for r in rows:
        out.append({k: v for k, v in r.items() if k not in INTERNAL_ONLY_FIELDS})
    return out


def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def bulk_insert(rows, model):
    if not rows:
        return
    db = SessionLocal()
    try:
        db.bulk_insert_mappings(model, rows)
        db.commit()
    finally:
        db.close()


def export_csv(name, rows):
    if not rows:
        return
    df = pd.DataFrame(rows)
    out_dir = os.path.join(DATA_DIR, "synthetic") if name != "anomaly_labels" else os.path.join(DATA_DIR, "ground_truth")
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(os.path.join(out_dir, f"{name}.csv"), index=False)


def main(seed: int = 42, n_merchants: int = 45, sim_days: int = 60, target_payments: int = 11000):
    t0 = time.time()
    print(f"[seed] generating synthetic dataset (seed={seed}, merchants={n_merchants}, "
          f"days={sim_days}, target_payments={target_payments}) ...")
    gen = generate_dataset(seed=seed, n_merchants=n_merchants, sim_days=sim_days,
                            target_payments=target_payments)

    print(f"[seed] generated: merchants={len(gen.merchants)} customers={len(gen.customers)} "
          f"orders={len(gen.orders)} payments={len(gen.payments)} refunds={len(gen.refunds)} "
          f"settlements={len(gen.settlements)} settlement_items={len(gen.settlement_items)} "
          f"disputes={len(gen.disputes)} fees={len(gen.fees)} "
          f"bank_txns={len(gen.bank_transactions)} ledger_entries={len(gen.ledger_entries)} "
          f"labels={len(gen.labels)}")

    print("[seed] resetting database ...")
    reset_db()

    datasets = {
        "merchants": _clean(gen.merchants),
        "customers": gen.customers,
        "orders": gen.orders,
        "payments": _clean(gen.payments),
        "refunds": _clean(gen.refunds),
        "settlements": gen.settlements,
        "settlement_items": gen.settlement_items,
        "disputes": gen.disputes,
        "fees": gen.fees,
        "bank_transactions": gen.bank_transactions,
        "ledger_entries": gen.ledger_entries,
        "anomaly_labels": gen.labels,
    }

    model_map = {
        "merchants": orm.Merchant, "customers": orm.Customer, "orders": orm.Order,
        "payments": orm.Payment, "refunds": orm.Refund, "settlements": orm.Settlement,
        "settlement_items": orm.SettlementItem, "disputes": orm.Dispute, "fees": orm.Fee,
        "bank_transactions": orm.BankTransaction, "ledger_entries": orm.LedgerEntry,
        "anomaly_labels": orm.AnomalyLabel,
    }

    for name, rows in datasets.items():
        print(f"[seed] loading {name} ({len(rows)} rows) ...")
        bulk_insert(rows, model_map[name])
        export_csv(name, rows)

    meta = {
        "seed": seed, "n_merchants": n_merchants, "sim_days": sim_days,
        "target_payments": target_payments, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {k: len(v) for k, v in datasets.items()},
    }
    with open(os.path.join(DATA_DIR, "synthetic", "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"[seed] done in {time.time()-t0:.1f}s")

    print("[seed] running detection + evaluation benchmark ...")
    from app.services.pipeline import run_full_pipeline  # noqa: E402
    run_full_pipeline()
    print("[seed] pipeline complete.")


if __name__ == "__main__":
    main()
