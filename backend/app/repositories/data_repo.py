"""Loads the full synthetic dataset from SQLite into pandas DataFrames.

Single place the detection pipeline pulls raw data from — keeps engines
storage-agnostic (swap SQLite for Postgres by changing DATABASE_URL only).
"""
import pandas as pd
from sqlalchemy import text

from app.core.db import engine


def _read(table: str) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(f"SELECT * FROM {table}"), conn)


class DataBundle:
    def __init__(self):
        self.merchants = _read("merchants")
        self.customers = _read("customers")
        self.orders = _read("orders")
        self.payments = _read("payments")
        self.refunds = _read("refunds")
        self.settlements = _read("settlements")
        self.settlement_items = _read("settlement_items")
        self.disputes = _read("disputes")
        self.fees = _read("fees")
        self.bank_transactions = _read("bank_transactions")
        self.ledger_entries = _read("ledger_entries")
        self.labels = _read("anomaly_labels")

        for df, cols in [
            (self.payments, ["created_at", "captured_at"]),
            (self.refunds, ["created_at", "processed_at"]),
            (self.settlements, ["created_at", "settled_at"]),
            (self.bank_transactions, ["value_date"]),
            (self.disputes, ["created_at", "resolved_at"]),
            (self.ledger_entries, ["created_at"]),
            (self.labels, ["injected_at"]),
            (self.orders, ["created_at"]),
        ]:
            for c in cols:
                if c in df.columns:
                    df[c] = pd.to_datetime(df[c], errors="coerce")


def load_bundle() -> DataBundle:
    return DataBundle()
