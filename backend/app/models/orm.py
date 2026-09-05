"""SQLAlchemy ORM models for the Financial Control Agent.

Core financial entities mirror Razorpay concepts (orders, payments, refunds,
settlements, settlement items, disputes, fees). Control-layer entities
(Exception, AuditEvent, Action, AnomalyLabel) sit on top and are never
written to by anything other than the deterministic engines / bounded
action layer.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, DateTime, ForeignKey, Boolean, Text, JSON
)
from sqlalchemy.orm import relationship

from app.core.db import Base


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Merchant(Base):
    __tablename__ = "merchants"
    id = Column(String, primary_key=True, default=lambda: uid("mer"))
    name = Column(String, nullable=False)
    category = Column(String)
    risk_tier = Column(String, default="standard")
    mdr_rate = Column(Float, default=0.02)  # merchant discount rate baseline
    onboarded_at = Column(DateTime, default=datetime.utcnow)

    customers = relationship("Customer", back_populates="merchant")
    orders = relationship("Order", back_populates="merchant")


class Customer(Base):
    __tablename__ = "customers"
    id = Column(String, primary_key=True, default=lambda: uid("cus"))
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    name = Column(String)
    email = Column(String)

    merchant = relationship("Merchant", back_populates="customers")


class Order(Base):
    __tablename__ = "orders"
    id = Column(String, primary_key=True, default=lambda: uid("order"))
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    customer_id = Column(String, ForeignKey("customers.id"))
    amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    status = Column(String, default="created")
    created_at = Column(DateTime, default=datetime.utcnow)

    merchant = relationship("Merchant", back_populates="orders")


class Payment(Base):
    __tablename__ = "payments"
    id = Column(String, primary_key=True, default=lambda: uid("pay"))
    order_id = Column(String, ForeignKey("orders.id"), index=True)
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    amount = Column(Float, nullable=False)
    method = Column(String)  # card/upi/netbanking/wallet
    status = Column(String, default="captured")  # created/authorized/captured/failed
    fee = Column(Float, default=0.0)  # actual fee charged
    tax = Column(Float, default=0.0)  # GST on fee
    expected_fee = Column(Float, default=0.0)  # deterministic baseline fee
    cohort = Column(String)  # payment cohort tag e.g. method+day bucket
    created_at = Column(DateTime, default=datetime.utcnow)
    captured_at = Column(DateTime)


class Refund(Base):
    __tablename__ = "refunds"
    id = Column(String, primary_key=True, default=lambda: uid("rfnd"))
    payment_id = Column(String, ForeignKey("payments.id"), index=True)
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    amount = Column(Float, nullable=False)
    status = Column(String, default="processed")  # initiated/processed/failed
    reason = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime)
    speed = Column(String, default="normal")  # instant/normal


class Settlement(Base):
    __tablename__ = "settlements"
    id = Column(String, primary_key=True, default=lambda: uid("stl"))
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    utr = Column(String)
    amount = Column(Float, nullable=False)
    status = Column(String, default="processed")
    created_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime)


class SettlementItem(Base):
    __tablename__ = "settlement_items"
    id = Column(String, primary_key=True, default=lambda: uid("sti"))
    settlement_id = Column(String, ForeignKey("settlements.id"), index=True)
    payment_id = Column(String, ForeignKey("payments.id"), nullable=True)
    refund_id = Column(String, ForeignKey("refunds.id"), nullable=True)
    amount = Column(Float, nullable=False)
    item_type = Column(String)  # payment/refund/fee/adjustment/reserve


class Dispute(Base):
    __tablename__ = "disputes"
    id = Column(String, primary_key=True, default=lambda: uid("disp"))
    payment_id = Column(String, ForeignKey("payments.id"), index=True)
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    amount = Column(Float, nullable=False)
    status = Column(String, default="open")  # open/won/lost/reserve_held
    reason = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)


class Fee(Base):
    __tablename__ = "fees"
    id = Column(String, primary_key=True, default=lambda: uid("fee"))
    payment_id = Column(String, ForeignKey("payments.id"), index=True)
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    expected_fee = Column(Float, default=0.0)
    actual_fee = Column(Float, default=0.0)
    fee_type = Column(String, default="mdr")


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    id = Column(String, primary_key=True, default=lambda: uid("bnk"))
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    amount = Column(Float, nullable=False)
    utr = Column(String)
    value_date = Column(DateTime)
    matched_settlement_id = Column(String, ForeignKey("settlements.id"), nullable=True)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id = Column(String, primary_key=True, default=lambda: uid("led"))
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    account = Column(String)
    debit = Column(Float, default=0.0)
    credit = Column(Float, default=0.0)
    ref_type = Column(String)
    ref_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Ground truth (evaluation only — never consumed by detection engines)
# ---------------------------------------------------------------------------
class AnomalyLabel(Base):
    __tablename__ = "anomaly_labels"
    id = Column(String, primary_key=True, default=lambda: uid("lbl"))
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    scenario_type = Column(String, index=True)
    entity_type = Column(String)
    entity_id = Column(String, index=True)
    expected_amount = Column(Float, default=0.0)
    is_true_anomaly = Column(Boolean, default=True)
    split = Column(String, default="holdout")  # calibration/holdout
    injected_at = Column(DateTime, default=datetime.utcnow)
    description = Column(Text)


# ---------------------------------------------------------------------------
# Control layer
# ---------------------------------------------------------------------------
class Exception_(Base):
    __tablename__ = "exceptions"
    id = Column(String, primary_key=True, default=lambda: uid("exc"))
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    exception_type = Column(String, index=True)
    entity_type = Column(String)
    entity_id = Column(String, index=True)
    severity = Column(String)  # low/medium/high/critical
    status = Column(String, default="open")  # open/auto_resolved/review_required/escalated/resolved
    detected_at = Column(DateTime, default=datetime.utcnow)
    window_start = Column(DateTime)
    window_end = Column(DateTime)

    money_at_risk = Column(Float, default=0.0)
    recoverable_amount = Column(Float, default=0.0)
    money_at_risk_breakdown = Column(JSON)  # list of {component, amount, source_ids}

    detector = Column(String)  # which detector raised it
    confidence = Column(Float, default=0.0)
    evidence = Column(JSON)  # list of {type, id, summary, fields}

    root_cause = Column(JSON)  # structured diagnostic tree result
    root_cause_label = Column(String)
    case_id = Column(String, nullable=True, index=True)  # set by group_related_exceptions action

    recommended_action = Column(String)
    action_category = Column(String)  # SAFE_AUTO_ACTION/REVIEW_REQUIRED/ESCALATE
    explanation = Column(Text)

    ground_truth_label_id = Column(String, nullable=True)


class Action(Base):
    __tablename__ = "actions"
    id = Column(String, primary_key=True, default=lambda: uid("act"))
    exception_id = Column(String, ForeignKey("exceptions.id"), index=True)
    action_type = Column(String)
    category = Column(String)
    status = Column(String, default="pending")  # pending/executed/rejected/reversed
    payload = Column(JSON)
    result = Column(JSON)
    idempotency_key = Column(String, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(String, primary_key=True, default=lambda: uid("aud"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    entity_type = Column(String)
    entity_id = Column(String, index=True)
    trigger = Column(String)
    evidence_consulted = Column(JSON)
    calculations = Column(JSON)
    model_or_rule = Column(String)
    decision = Column(Text)
    confidence = Column(Float)
    action = Column(String)
    execution_outcome = Column(String)
    human_review_required = Column(Boolean, default=False)
