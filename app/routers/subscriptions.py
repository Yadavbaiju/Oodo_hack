from datetime import date, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import joinedload
from ..billing import add_period
from ..crud import serialize
from ..database import get_db
from ..deps import roles, my_customer_id
from ..models import Subscription, SubscriptionLine, Plan, Product, Variant, QuotationTemplate, Customer

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])
ORDER = ["draft", "quotation", "confirmed", "active"]
ANY = Depends(roles("admin", "staff", "customer"))
TEAM = Depends(roles("admin", "staff"))


class LineIn(BaseModel):
    product_id: int
    variant_id: Optional[int] = None
    quantity: float = Field(1, gt=0)


class SubIn(BaseModel):
    customer_id: int
    plan_id: int
    start_date: date
    expiry_date: Optional[date] = None
    payment_terms: str = "Net 30"
    lines: List[LineIn] = []


class FromTemplate(BaseModel):
    template_id: int
    customer_id: int
    start_date: date
    payment_terms: str = "Net 30"


def ser(s, detail=False):
    d = serialize(s)
    d["customer_name"] = s.customer.name if s.customer else None
    d["plan_name"] = s.plan.name if s.plan else None
    if detail:
        d["lines"] = [{**serialize(l), "product_name": l.product.name,
                       "variant": f"{l.variant.attribute}: {l.variant.value}" if l.variant else None,
                       "tax_rate": l.tax.rate if l.tax else 0,
                       "amount": round(l.quantity * l.unit_price, 2)} for l in s.lines]
        d["total"] = round(sum(l["amount"] for l in d["lines"]), 2)
    return d


def make_line(db, product_id, variant_id, qty):
    p = db.get(Product, product_id)
    if not p: raise HTTPException(404, f"Product {product_id} not found")
    price = p.sales_price
    if variant_id:
        v = db.get(Variant, variant_id)
        if not v or v.product_id != p.id: raise HTTPException(422, "Variant does not belong to this product")
        price += v.extra_price or 0
    return SubscriptionLine(product_id=p.id, variant_id=variant_id, quantity=qty, unit_price=price, tax_id=p.tax_id)


def check_plan(plan, start):
    if not plan or not plan.active: raise HTTPException(422, "Plan is not available")
    if (plan.start_date and start < plan.start_date) or (plan.end_date and start > plan.end_date):
        raise HTTPException(422, "Start date is outside the plan's availability window")


def load(db, sid, u):
    s = db.get(Subscription, sid)
    if not s: raise HTTPException(404, "Subscription not found")
    if u.role == "customer" and s.customer_id != my_customer_id(db, u): raise HTTPException(404, "Subscription not found")
    return s


@router.get("")
def list_subs(status: str = None, customer_id: int = None, q: str = None, page: int = 1, size: int = 50,
              db=Depends(get_db), u=ANY):
    qs = db.query(Subscription).options(joinedload(Subscription.customer), joinedload(Subscription.plan))
    if u.role == "customer": qs = qs.filter(Subscription.customer_id == my_customer_id(db, u))
    elif customer_id: qs = qs.filter(Subscription.customer_id == customer_id)
    if status: qs = qs.filter(Subscription.status == status)
    if q: qs = qs.filter(Subscription.number.ilike(f"%{q}%"))
    total = qs.count()
    items = qs.order_by(Subscription.id.desc()).offset((max(page, 1) - 1) * size).limit(min(size, 200)).all()
    return {"items": [ser(s) for s in items], "total": total, "page": page}


@router.get("/{sid}")
def get_sub(sid: int, db=Depends(get_db), u=ANY):
    return ser(load(db, sid, u), detail=True)


@router.post("")
def create(body: SubIn, db=Depends(get_db), u=TEAM):
    plan = db.get(Plan, body.plan_id)
    check_plan(plan, body.start_date)
    if body.expiry_date and body.expiry_date < body.start_date: raise HTTPException(422, "Expiry date cannot be before the start date")
    if not db.get(Customer, body.customer_id): raise HTTPException(404, "Customer not found")
    s = Subscription(customer_id=body.customer_id, plan_id=plan.id, start_date=body.start_date,
                     expiry_date=body.expiry_date or plan.end_date or add_period(body.start_date, "yearly") - timedelta(days=1),
                     payment_terms=body.payment_terms, status="draft", next_billing_date=body.start_date)
    s.lines = [make_line(db, l.product_id, l.variant_id, l.quantity) for l in body.lines]
    db.add(s); db.flush()
    s.number = f"SUB-{s.id:05d}"
    db.commit(); db.refresh(s)
    return ser(s, True)


@router.post("/from-template")
def from_template(body: FromTemplate, db=Depends(get_db), u=TEAM):
    t = db.get(QuotationTemplate, body.template_id)
    if not t: raise HTTPException(404, "Template not found")
    check_plan(t.plan, body.start_date)
    s = Subscription(customer_id=body.customer_id, plan_id=t.plan_id, start_date=body.start_date,
                     expiry_date=t.plan.end_date or add_period(body.start_date, "yearly") - timedelta(days=1),
                     payment_terms=body.payment_terms, status="quotation", next_billing_date=body.start_date,
                     quote_valid_until=date.today() + timedelta(days=t.validity_days or 30))
    s.lines = [make_line(db, l.product_id, l.variant_id, l.quantity) for l in t.lines]
    db.add(s); db.flush()
    s.number = f"SUB-{s.id:05d}"
    db.commit(); db.refresh(s)
    return ser(s, True)


@router.post("/{sid}/advance")
def advance(sid: int, db=Depends(get_db), u=TEAM):
    """Draft -> Quotation -> Confirmed -> Active (one step at a time)."""
    s = load(db, sid, u)
    if s.status not in ORDER[:-1]: raise HTTPException(400, f"Cannot advance a {s.status} subscription")
    nxt = ORDER[ORDER.index(s.status) + 1]
    if s.status == "quotation" and s.quote_valid_until and s.quote_valid_until < date.today():
        raise HTTPException(400, "This quotation has expired")
    if nxt == "confirmed":
        if not s.lines: raise HTTPException(400, "Add at least one product line first")
        if sum(l.quantity for l in s.lines) < (s.plan.min_quantity or 0):
            raise HTTPException(400, f"Plan requires a minimum quantity of {s.plan.min_quantity}")
    s.status = nxt
    db.commit()
    return ser(s)


def _plan_flag(s, flag, label):
    if not getattr(s.plan, flag): raise HTTPException(403, f"This plan does not allow {label}")


@router.post("/{sid}/pause")
def pause(sid: int, db=Depends(get_db), u=ANY):
    s = load(db, sid, u); _plan_flag(s, "allow_pause", "pausing")
    if s.status != "active": raise HTTPException(400, "Only active subscriptions can be paused")
    s.paused = True; db.commit(); return ser(s)


@router.post("/{sid}/resume")
def resume(sid: int, db=Depends(get_db), u=ANY):
    s = load(db, sid, u)
    if not s.paused: raise HTTPException(400, "Subscription is not paused")
    s.paused = False
    while s.next_billing_date < date.today():   # skip paused periods instead of back-billing them
        s.next_billing_date = add_period(s.next_billing_date, s.plan.billing_period, s.start_date.day)
    db.commit(); return ser(s)


@router.post("/{sid}/close")
def close(sid: int, db=Depends(get_db), u=ANY):
    s = load(db, sid, u); _plan_flag(s, "allow_close", "early closing")
    if s.status == "closed": raise HTTPException(400, "Already closed")
    s.status, s.paused = "closed", False
    db.commit(); return ser(s)


@router.post("/{sid}/renew")
def renew(sid: int, db=Depends(get_db), u=ANY):
    s = load(db, sid, u); _plan_flag(s, "allow_renew", "renewal")
    base = max(s.expiry_date or date.today(), date.today())
    s.expiry_date = add_period(base, s.plan.billing_period)
    if s.status == "closed":
        s.status = "active"
        s.next_billing_date = date.today()
    db.commit(); return ser(s)
