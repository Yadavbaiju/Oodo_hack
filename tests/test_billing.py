"""Unit tests for the invoice engine: month-end date drift and rounding. No database needed."""
import random
from datetime import date
from types import SimpleNamespace as NS
from app.billing import add_period, build_invoice


def test_monthly_keeps_anchor_day_across_short_months():
    d, seen = date(2026, 1, 31), []
    for _ in range(6):
        seen.append(d); d = add_period(d, "monthly", 31)
    assert seen == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31),
                    date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30)]


def test_yearly_feb_29_returns_in_leap_years():
    d = date(2028, 2, 29)
    for expected in (date(2029, 2, 28), date(2030, 2, 28), date(2031, 2, 28), date(2032, 2, 29)):
        d = add_period(d, "yearly", 29)
        assert d == expected


def test_add_period_without_anchor_behaves_as_before():
    assert add_period(date(2026, 1, 15), "monthly") == date(2026, 2, 15)
    assert add_period(date(2026, 1, 15), "weekly") == date(2026, 1, 22)
    assert add_period(date(2026, 12, 15), "monthly") == date(2027, 1, 15)


# ---- minimal fakes so build_invoice runs without a database ----
class _Q:
    def filter_by(self, **k): return self
    def first(self): return None


class _DB:
    n = 0
    def query(self, *a): return _Q()
    def add(self, o):
        if o.__class__.__name__ == "Invoice": _DB.n += 1; o.id = _DB.n
    def flush(self): pass


def _sub(lines, start=date(2026, 1, 31)):
    return NS(id=1, customer_id=1, payment_terms="Net 30", start_date=start,
              plan=NS(name="P", price=0, billing_period="monthly"), lines=lines)


def _line(qty, unit, rate):
    return NS(product=NS(name="Prod"), variant=None, product_id=1, quantity=qty, unit_price=unit, tax=NS(rate=rate))


def _disc(pct):
    return NS(id=1, name="Volume", scope="subscription", subscription_id=None, kind="percent", value=pct,
              min_purchase=0, min_quantity=0, start_date=None, end_date=None, usage_limit=None, used_count=0)


def test_known_invoice_total():
    inv = build_invoice(_DB(), _sub([_line(5, 1560, 18)]), date(2026, 10, 31), date(2026, 10, 31), [_disc(10)])
    assert (inv.subtotal, inv.discount_total, inv.tax_total, inv.total) == (7800, 780, 1263.6, 8283.6)


def test_period_end_uses_anchor_day():
    inv = build_invoice(_DB(), _sub([_line(1, 100, 0)]), date(2026, 2, 28), date(2026, 2, 28), [])
    assert inv.period_end == date(2026, 3, 30)   # next period starts Mar 31 -> ends Mar 30


def test_total_always_equals_its_stored_parts():
    random.seed(1)
    for _ in range(3000):
        lines = [_line(random.choice([1, 2, 3, 5, 7]), round(random.uniform(10, 2000), 2), random.choice([0, 5, 12, 18, 28]))
                 for _ in range(random.randint(1, 3))]
        discounts = [_disc(random.choice([5, 10, 15]))] if random.random() < 0.7 else []
        inv = build_invoice(_DB(), _sub(lines), date(2026, 10, 31), date(2026, 10, 31), discounts)
        assert inv.total == round(inv.subtotal - inv.discount_total + inv.tax_total, 2)
