from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy import func, cast, String
from ..database import get_db
from ..deps import roles
from ..models import Subscription, SubscriptionLine, Plan, Invoice, Payment

router = APIRouter(prefix="/api/reports", tags=["reports"])
FACTOR = {"daily": 30.0, "weekly": 52 / 12, "monthly": 1.0, "yearly": 1 / 12}


@router.get("/summary")
def summary(date_from: date = None, date_to: date = None, db=Depends(get_db), u=Depends(roles("admin", "staff"))):
    today = date.today()
    pq = db.query(func.coalesce(func.sum(Payment.amount), 0))
    iq = db.query(func.coalesce(func.sum(Invoice.total), 0)).filter(Invoice.status.in_(["confirmed", "paid"]))
    if date_from: pq, iq = pq.filter(Payment.date >= date_from), iq.filter(Invoice.issue_date >= date_from)
    if date_to: pq, iq = pq.filter(Payment.date <= date_to), iq.filter(Invoice.issue_date <= date_to)
    by_status = dict(db.query(Subscription.status, func.count()).group_by(Subscription.status).all())
    outstanding = db.query(func.coalesce(func.sum(Invoice.total - Invoice.amount_paid), 0)).filter(Invoice.status == "confirmed").scalar()
    od = db.query(func.count(), func.coalesce(func.sum(Invoice.total - Invoice.amount_paid), 0)).filter(
        Invoice.status == "confirmed", Invoice.due_date < today).one()
    inv_counts = dict(db.query(Invoice.status, func.count()).group_by(Invoice.status).all())
    line_sums = dict(db.query(SubscriptionLine.subscription_id, func.sum(SubscriptionLine.quantity * SubscriptionLine.unit_price))
                     .group_by(SubscriptionLine.subscription_id).all())
    rows = db.query(Subscription.id, Plan.price, Plan.billing_period).join(Plan, Plan.id == Subscription.plan_id).filter(
        Subscription.status == "active", Subscription.paused == False).all()
    mrr = sum(((p or 0) + (line_sums.get(i) or 0)) * FACTOR.get(per, 1) for i, p, per in rows)
    month = func.substr(cast(Payment.date, String), 1, 7)
    monthly = db.query(month, func.sum(Payment.amount)).group_by(month).order_by(month).all()
    return {"active_subscriptions": by_status.get("active", 0), "subscriptions_by_status": by_status,
            "revenue_collected": round(pq.scalar(), 2), "total_invoiced": round(iq.scalar(), 2),
            "outstanding": round(outstanding, 2), "overdue_count": od[0], "overdue_amount": round(od[1], 2),
            "invoices_by_status": inv_counts, "mrr": round(mrr, 2),
            "monthly_revenue": [{"month": m, "amount": round(a, 2)} for m, a in monthly[-12:]]}
