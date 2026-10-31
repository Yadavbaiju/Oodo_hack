import calendar, re
from datetime import date, timedelta
from .models import Invoice, InvoiceLine


def add_period(d: date, period: str) -> date:
    if period == "daily": return d + timedelta(days=1)
    if period == "weekly": return d + timedelta(days=7)
    months = 1 if period == "monthly" else 12
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def terms_days(terms: str) -> int:
    m = re.search(r"\d+", terms or "")
    return int(m.group()) if m else 0


def eligible(d, base, qty, on):
    if d.start_date and on < d.start_date: return False
    if d.end_date and on > d.end_date: return False
    if d.usage_limit is not None and (d.used_count or 0) >= d.usage_limit: return False
    if d.min_purchase and base < d.min_purchase: return False
    if d.min_quantity and qty < d.min_quantity: return False
    return True


def discount_amount(d, base):
    raw = base * d.value / 100 if d.kind == "percent" else d.value
    return round(max(0.0, min(base, raw)), 2)


def build_invoice(db, sub, period_start: date, today: date, discounts: list):
    """Creates ONE draft invoice for (subscription, period). Returns None if it already exists."""
    if db.query(Invoice.id).filter_by(subscription_id=sub.id, period_start=period_start).first():
        return None
    plan = sub.plan
    period_end = add_period(period_start, plan.billing_period) - timedelta(days=1)
    items = []
    if plan.price:
        items.append(dict(desc=f"{plan.name} - plan fee", pid=None, qty=1, unit=plan.price, rate=0.0))
    for l in sub.lines:
        name = l.product.name + (f" ({l.variant.attribute}: {l.variant.value})" if l.variant else "")
        items.append(dict(desc=name, pid=l.product_id, qty=l.quantity, unit=l.unit_price, rate=l.tax.rate if l.tax else 0.0))
    for it in items:
        it["gross"], it["disc"] = round(it["qty"] * it["unit"], 2), 0.0

    disc_lines, used = [], set()
    # 1) product-level discounts
    for d in discounts:
        if d.scope != "product": continue
        for it in items:
            if it["pid"] == d.product_id and eligible(d, it["gross"] - it["disc"], it["qty"], today):
                a = discount_amount(d, it["gross"] - it["disc"])
                if a > 0:
                    it["disc"] += a; used.add(d.id)
                    disc_lines.append((f"Discount: {d.name} ({it['desc']})", a))
    subtotal = round(sum(i["gross"] for i in items), 2)
    after_product = round(subtotal - sum(i["disc"] for i in items), 2)
    tax = sum(round((i["gross"] - i["disc"]) * i["rate"] / 100, 2) for i in items)
    # 2) subscription-level discounts
    sub_disc = 0.0
    total_qty = sum(i["qty"] for i in items if i["pid"])
    for d in discounts:
        if d.scope != "subscription" or d.subscription_id not in (None, sub.id): continue
        base = after_product - sub_disc
        if eligible(d, base, total_qty, today):
            a = discount_amount(d, base)
            if a > 0:
                sub_disc += a; used.add(d.id)
                disc_lines.append((f"Discount: {d.name}", a))
    if after_product > 0:
        tax = tax * (1 - sub_disc / after_product)  # tax follows the discounted amount
    discount_total = round(sum(i["disc"] for i in items) + sub_disc, 2)

    inv = Invoice(subscription_id=sub.id, customer_id=sub.customer_id, period_start=period_start, period_end=period_end,
                  issue_date=today, due_date=today + timedelta(days=terms_days(sub.payment_terms)), status="draft",
                  subtotal=subtotal, discount_total=discount_total, tax_total=round(tax, 2),
                  total=round(subtotal - discount_total + tax, 2))
    db.add(inv); db.flush()
    inv.number = f"INV-{inv.id:06d}"
    for i in items:
        db.add(InvoiceLine(invoice_id=inv.id, description=i["desc"], quantity=i["qty"], unit_price=i["unit"], tax_rate=i["rate"], amount=i["gross"]))
    for desc, a in disc_lines:
        db.add(InvoiceLine(invoice_id=inv.id, description=desc, quantity=1, unit_price=-a, tax_rate=0, amount=-a))
    for d in discounts:
        if d.id in used: d.used_count = (d.used_count or 0) + 1
    return inv
