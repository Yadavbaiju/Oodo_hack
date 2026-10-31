import os
from datetime import date, timedelta
from .models import User, Customer, Tax, Product, Variant, Plan, QuotationTemplate, TemplateLine, Discount
from .security import hash_pw


def seed(db):
    if db.query(User).count():
        return
    db.add(User(email=os.getenv("ADMIN_EMAIL", "admin@brightloop.com"), name="Admin", role="admin",
                password_hash=hash_pw(os.getenv("ADMIN_PASSWORD", "Admin@12345"))))
    gst = Tax(name="GST 18%", rate=18); db.add(gst); db.flush()
    crm = Product(name="Brightloop CRM", type="software", sales_price=1000, cost_price=400, notes="Core CRM seat", tax_id=gst.id)
    db.add(crm); db.flush()
    db.add_all([Variant(product_id=crm.id, attribute="Brand", value="Odoo", extra_price=560),
                Variant(product_id=crm.id, attribute="Brand", value="Standard", extra_price=0)])
    addon = Product(name="Analytics Add-on", type="service", sales_price=250, cost_price=60, tax_id=gst.id)
    db.add(addon)
    monthly = Plan(name="Business Monthly", price=0, billing_period="monthly", min_quantity=1, start_date=date.today() - timedelta(days=30), end_date=date.today() + timedelta(days=700), allow_pause=True)
    yearly = Plan(name="Enterprise Yearly", price=500, billing_period="yearly", min_quantity=5, auto_close=True)
    db.add_all([monthly, yearly]); db.flush()
    t = QuotationTemplate(name="Enterprise starter", validity_days=30, plan_id=yearly.id); db.add(t); db.flush()
    db.add(TemplateLine(template_id=t.id, product_id=crm.id, quantity=5))
    db.add(Discount(name="Volume 10%", kind="percent", value=10, min_quantity=5, scope="subscription", usage_limit=100,
                    start_date=date.today() - timedelta(days=30), end_date=date.today() + timedelta(days=365)))
    c = User(email="demo@customer.com", name="Demo Shop", role="customer", password_hash=hash_pw("Customer@123"))
    db.add(c); db.flush()
    db.add(Customer(user_id=c.id, name="Demo Shop", email=c.email, company="Demo Shop Pvt Ltd"))
    db.commit()
