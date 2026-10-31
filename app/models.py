from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, default="")
    password_hash = Column(String, nullable=False)
    role = Column(String, default="customer", index=True)  # admin | staff | customer
    created_at = Column(DateTime, default=datetime.utcnow)


class ResetToken(Base):
    __tablename__ = "reset_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    token = Column(String, unique=True, index=True)
    expires_at = Column(DateTime)
    used = Column(Boolean, default=False)


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, index=True)
    phone = Column(String)
    company = Column(String)
    address = Column(Text)


class Tax(Base):
    __tablename__ = "taxes"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    rate = Column(Float, nullable=False, default=0)  # percent


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, default="software")
    sales_price = Column(Float, nullable=False, default=0)
    cost_price = Column(Float, default=0)
    notes = Column(Text)
    tax_id = Column(Integer, ForeignKey("taxes.id"), nullable=True)
    tax = relationship("Tax")
    variants = relationship("Variant", cascade="all,delete-orphan")


class Variant(Base):
    __tablename__ = "variants"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    attribute = Column(String, nullable=False)  # e.g. Brand
    value = Column(String, nullable=False)      # e.g. Odoo
    extra_price = Column(Float, default=0)      # e.g. 560


class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False, default=0)
    billing_period = Column(String, nullable=False, default="monthly")  # daily|weekly|monthly|yearly
    min_quantity = Column(Integer, default=1)
    start_date = Column(Date)
    end_date = Column(Date)
    auto_close = Column(Boolean, default=False)
    allow_close = Column(Boolean, default=True)
    allow_pause = Column(Boolean, default=True)
    allow_renew = Column(Boolean, default=True)
    active = Column(Boolean, default=True)


class QuotationTemplate(Base):
    __tablename__ = "quotation_templates"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    validity_days = Column(Integer, default=30)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    plan = relationship("Plan")
    lines = relationship("TemplateLine", cascade="all,delete-orphan")


class TemplateLine(Base):
    __tablename__ = "template_lines"
    id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey("quotation_templates.id"), index=True, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    variant_id = Column(Integer, ForeignKey("variants.id"), nullable=True)
    quantity = Column(Float, default=1)


class Discount(Base):
    __tablename__ = "discounts"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="percent")  # fixed | percent
    value = Column(Float, nullable=False)
    min_purchase = Column(Float, default=0)
    min_quantity = Column(Float, default=0)
    start_date = Column(Date)
    end_date = Column(Date)
    usage_limit = Column(Integer)           # null = unlimited
    used_count = Column(Integer, default=0)
    scope = Column(String, default="subscription")  # product | subscription
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)  # null = all subscriptions


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    number = Column(String, unique=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True, nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    expiry_date = Column(Date)
    payment_terms = Column(String, default="Net 30")
    status = Column(String, default="draft", index=True)  # draft|quotation|confirmed|active|closed
    paused = Column(Boolean, default=False)
    next_billing_date = Column(Date, index=True)
    quote_valid_until = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)
    customer = relationship("Customer")
    plan = relationship("Plan")
    lines = relationship("SubscriptionLine", cascade="all,delete-orphan")


class SubscriptionLine(Base):
    __tablename__ = "subscription_lines"
    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), index=True, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    variant_id = Column(Integer, ForeignKey("variants.id"), nullable=True)
    quantity = Column(Float, default=1)
    unit_price = Column(Float, default=0)
    tax_id = Column(Integer, ForeignKey("taxes.id"), nullable=True)
    product = relationship("Product")
    variant = relationship("Variant")
    tax = relationship("Tax")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("subscription_id", "period_start", name="uq_invoice_period"),)  # never bill twice
    id = Column(Integer, primary_key=True)
    number = Column(String, unique=True, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True, nullable=False)
    period_start = Column(Date)
    period_end = Column(Date)
    issue_date = Column(Date)
    due_date = Column(Date, index=True)
    status = Column(String, default="draft", index=True)  # draft|confirmed|paid|cancelled
    sent = Column(Boolean, default=False)
    subtotal = Column(Float, default=0)
    discount_total = Column(Float, default=0)
    tax_total = Column(Float, default=0)
    total = Column(Float, default=0)
    amount_paid = Column(Float, default=0)
    customer = relationship("Customer")
    subscription = relationship("Subscription")
    lines = relationship("InvoiceLine", cascade="all,delete-orphan")
    payments = relationship("Payment", cascade="all,delete-orphan")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), index=True, nullable=False)
    description = Column(String)
    quantity = Column(Float, default=1)
    unit_price = Column(Float, default=0)
    tax_rate = Column(Float, default=0)
    amount = Column(Float, default=0)  # negative for discount lines


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), index=True, nullable=False)
    method = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    date = Column(Date, nullable=False, index=True)
    note = Column(Text)
