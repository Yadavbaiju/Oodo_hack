from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import joinedload
from ..billing import add_period, build_invoice
from ..crud import serialize
from ..database import get_db
from ..deps import roles, my_customer_id
from ..mail import send_email
from ..models import Invoice, Payment, Subscription, Discount, Plan

router = APIRouter(prefix="/api", tags=["invoices"])
ANY = Depends(roles("admin", "staff", "customer"))
TEAM = Depends(roles("admin", "staff"))


def ser(i, detail=False):
    d = serialize(i)
    d["customer_name"] = i.customer.name if i.customer else None
    d["outstanding"] = round(i.total - i.amount_paid, 2) if i.status in ("confirmed", "draft") else 0
    d["overdue"] = bool(i.status == "confirmed" and i.due_date and i.due_date < date.today())
    if detail:
        d["lines"] = [serialize(l) for l in i.lines]
        d["payments"] = [serialize(p) for p in i.payments]
    return d


def load(db, iid, u):
    i = db.get(Invoice, iid)
    if not i or (u.role == "customer" and i.customer_id != my_customer_id(db, u)):
        raise HTTPException(404, "Invoice not found")
    return i


@router.get("/invoices")
def list_invoices(status: str = None, overdue: bool = False, customer_id: int = None, subscription_id: int = None,
                  q: str = None, page: int = 1, size: int = 50, db=Depends(get_db), u=ANY):
    qs = db.query(Invoice).options(joinedload(Invoice.customer))
    if u.role == "customer": qs = qs.filter(Invoice.customer_id == my_customer_id(db, u))
    elif customer_id: qs = qs.filter(Invoice.customer_id == customer_id)
    if subscription_id: qs = qs.filter(Invoice.subscription_id == subscription_id)
    if status: qs = qs.filter(Invoice.status == status)
    if overdue: qs = qs.filter(Invoice.status == "confirmed", Invoice.due_date < date.today())
    if q: qs = qs.filter(Invoice.number.ilike(f"%{q}%"))
    total = qs.count()
    items = qs.order_by(Invoice.id.desc()).offset((max(page, 1) - 1) * size).limit(min(size, 200)).all()
    return {"items": [ser(i) for i in items], "total": total, "page": page}


@router.get("/invoices/{iid}")
def get_invoice(iid: int, db=Depends(get_db), u=ANY):
    return ser(load(db, iid, u), True)


@router.post("/invoices/{iid}/confirm")
def confirm(iid: int, db=Depends(get_db), u=TEAM):
    i = load(db, iid, u)
    if i.status != "draft": raise HTTPException(400, "Only draft invoices can be confirmed")
    i.status = "confirmed"; db.commit(); return ser(i)


@router.post("/invoices/{iid}/cancel")
def cancel(iid: int, db=Depends(get_db), u=TEAM):
    i = load(db, iid, u)
    if i.status in ("paid", "cancelled") or i.amount_paid > 0:
        raise HTTPException(400, "Paid or part-paid invoices cannot be cancelled")
    i.status = "cancelled"; db.commit(); return ser(i)


@router.post("/invoices/{iid}/send")
def send(iid: int, db=Depends(get_db), u=TEAM):
    i = load(db, iid, u)
    if i.status not in ("confirmed", "paid"): raise HTTPException(400, "Confirm the invoice before sending it")
    send_email(i.customer.email or "", f"Invoice {i.number} from Brightloop",
               f"Hello {i.customer.name},\n\nInvoice {i.number} for {i.total:.2f} is due on {i.due_date}.\n\nThank you,\nBrightloop Software")
    i.sent = True; db.commit(); return ser(i)


@router.get("/invoices/{iid}/print", response_class=HTMLResponse)
def print_invoice(iid: int, db=Depends(get_db), u=ANY):
    i = load(db, iid, u)
    rows = "".join(f"<tr><td>{l.description}</td><td>{l.quantity:g}</td><td>{l.unit_price:.2f}</td><td>{l.tax_rate:g}%</td><td>{l.amount:.2f}</td></tr>" for l in i.lines)
    return f"""<html><head><title>{i.number}</title><style>body{{font-family:sans-serif;max-width:760px;margin:30px auto}}
table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #ccc;padding:6px;text-align:left}}.r{{text-align:right}}</style></head><body>
<h1>Invoice {i.number}</h1><p><b>Brightloop Software</b><br>Bill to: {i.customer.name}<br>Issued {i.issue_date} &middot; Due {i.due_date} &middot; Status {i.status}</p>
<table><tr><th>Description</th><th>Qty</th><th>Unit</th><th>Tax</th><th>Amount</th></tr>{rows}</table>
<p class="r">Subtotal {i.subtotal:.2f}<br>Discount -{i.discount_total:.2f}<br>Tax {i.tax_total:.2f}<br><b>Total {i.total:.2f}</b><br>Paid {i.amount_paid:.2f}</p>
<script>window.print()</script></body></html>"""


@router.post("/billing/run")
def run_billing(as_of: Optional[date] = None, auto_confirm: bool = False, db=Depends(get_db), u=TEAM):
    """Creates every invoice that is due. Safe to run repeatedly: (subscription, period) is unique."""
    today = as_of or date.today()
    discounts = db.query(Discount).all()
    subs = db.query(Subscription).options(joinedload(Subscription.plan), joinedload(Subscription.lines)).filter(
        Subscription.status == "active", Subscription.paused == False, Subscription.next_billing_date <= today).all()
    created = []
    for s in subs:
        guard = 0
        while s.next_billing_date <= today and (not s.expiry_date or s.next_billing_date <= s.expiry_date) and guard < 60:
            inv = build_invoice(db, s, s.next_billing_date, today, discounts)
            if inv:
                if auto_confirm: inv.status = "confirmed"
                created.append(inv.id)
            s.next_billing_date = add_period(s.next_billing_date, s.plan.billing_period, s.start_date.day)
            guard += 1
    closed = db.query(Subscription).join(Plan, Plan.id == Subscription.plan_id).filter(
        Subscription.status == "active", Plan.auto_close == True, Subscription.expiry_date < today).all()
    for s in closed: s.status = "closed"
    db.commit()
    return {"as_of": today.isoformat(), "subscriptions_billed": len(subs), "invoices_created": len(created),
            "invoice_ids": created[:200], "auto_closed": len(closed)}


@router.get("/payments")
def list_payments(invoice_id: int = None, page: int = 1, size: int = 50, db=Depends(get_db), u=ANY):
    qs = db.query(Payment, Invoice.number).join(Invoice, Invoice.id == Payment.invoice_id)
    if u.role == "customer": qs = qs.filter(Invoice.customer_id == my_customer_id(db, u))
    if invoice_id: qs = qs.filter(Payment.invoice_id == invoice_id)
    total = qs.count()
    rows = qs.order_by(Payment.id.desc()).offset((max(page, 1) - 1) * size).limit(min(size, 200)).all()
    return {"items": [{**serialize(p), "invoice_number": n} for p, n in rows], "total": total, "page": page}


@router.post("/payments")
def record_payment(body: dict, db=Depends(get_db), u=TEAM):
    i = db.get(Invoice, int(body.get("invoice_id") or 0))
    if not i: raise HTTPException(404, "Invoice not found")
    if i.status != "confirmed": raise HTTPException(400, "Payments can only be recorded on confirmed invoices")
    try:
        amount = round(float(body.get("amount")), 2)
        pdate = date.fromisoformat(str(body.get("date") or date.today())[:10])
    except (TypeError, ValueError):
        raise HTTPException(422, "Enter a valid amount and date")
    if amount <= 0: raise HTTPException(422, "Amount must be greater than zero")
    if amount > round(i.total - i.amount_paid, 2) + 0.005: raise HTTPException(422, "Amount is more than the outstanding balance")
    if not body.get("method"): raise HTTPException(422, "Choose a payment method")
    db.add(Payment(invoice_id=i.id, method=body["method"], amount=amount, date=pdate, note=body.get("note")))
    i.amount_paid = round(i.amount_paid + amount, 2)
    if i.amount_paid >= i.total - 0.005: i.status = "paid"
    db.commit()
    return ser(i, True)
