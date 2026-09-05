"""Razorpay provider abstraction.

    MockRazorpayProvider  ---\
                               >---  same internal pipeline (detectors, root
    RazorpayTestModeProvider -/      cause, money-at-risk, action engine)

The rest of the system (detectors, repositories, API) only ever talks to
`DataBundle` (see app/repositories/data_repo.py), which is populated from
SQLite. This provider layer is the seam where a real Razorpay Test Mode
integration would plug in: it would pull payments/settlements/refunds via
the Razorpay API and load them into the same tables the synthetic generator
populates, so nothing downstream changes.

No credentials are available in this environment, so `RazorpayTestModeProvider`
is a structured stub — implemented enough to show exactly where the real
`razorpay` SDK calls go, but not wired to network calls. The product runs
fully on `MockRazorpayProvider` (i.e. the synthetic dataset) without it.
"""
import os
from abc import ABC, abstractmethod


class RazorpayProvider(ABC):
    @abstractmethod
    def fetch_payments(self, merchant_id: str, since=None) -> list[dict]:
        ...

    @abstractmethod
    def fetch_settlements(self, merchant_id: str, since=None) -> list[dict]:
        ...

    @abstractmethod
    def fetch_refunds(self, merchant_id: str, since=None) -> list[dict]:
        ...


class MockRazorpayProvider(RazorpayProvider):
    """Reads from the synthetic dataset already loaded into SQLite via
    app/services/seed.py — this is the provider used throughout the demo."""

    def __init__(self):
        from app.repositories.data_repo import load_bundle
        self._bundle = load_bundle()

    def fetch_payments(self, merchant_id: str, since=None) -> list[dict]:
        df = self._bundle.payments
        df = df[df["merchant_id"] == merchant_id]
        if since is not None:
            df = df[df["created_at"] >= since]
        return df.to_dict(orient="records")

    def fetch_settlements(self, merchant_id: str, since=None) -> list[dict]:
        df = self._bundle.settlements
        df = df[df["merchant_id"] == merchant_id]
        if since is not None:
            df = df[df["created_at"] >= since]
        return df.to_dict(orient="records")

    def fetch_refunds(self, merchant_id: str, since=None) -> list[dict]:
        df = self._bundle.refunds
        df = df[df["merchant_id"] == merchant_id]
        if since is not None:
            df = df[df["created_at"] >= since]
        return df.to_dict(orient="records")


class RazorpayTestModeProvider(RazorpayProvider):
    """Structured stub for real Razorpay Test Mode integration.

    Would use `razorpay.Client(auth=(key_id, key_secret))` and map
    `payment.entity.fetch_all` / `settlement.entity.fetch_all` /
    `refund.entity.fetch_all` responses onto the same field names the
    synthetic generator produces, then hand off to the same pipeline.
    Not called anywhere unless RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are set.
    """

    def __init__(self):
        self.key_id = os.environ.get("RAZORPAY_KEY_ID")
        self.key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
        if not (self.key_id and self.key_secret):
            raise RuntimeError("RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET not configured")

    def fetch_payments(self, merchant_id: str, since=None) -> list[dict]:
        raise NotImplementedError("Wire up razorpay-python client.payment.all() here")

    def fetch_settlements(self, merchant_id: str, since=None) -> list[dict]:
        raise NotImplementedError("Wire up razorpay-python client.settlement.all() here")

    def fetch_refunds(self, merchant_id: str, since=None) -> list[dict]:
        raise NotImplementedError("Wire up razorpay-python client.refund.all() here")


def get_provider() -> RazorpayProvider:
    if os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET"):
        try:
            return RazorpayTestModeProvider()
        except Exception:
            pass
    return MockRazorpayProvider()
