import os
os.environ["DATABASE_URL"] = "sqlite:///./test_flow.db"
if os.path.exists("test_flow.db"): os.remove("test_flow.db")
from datetime import date, timedelta
from fastapi.testclient import TestClient
from app.main import app


def test_full_flow():
    with TestClient(app) as c:
        # password rules + unique email
        assert c.post("/api/auth/signup", json={"email": "a@b.com", "password": "short"}).status_code == 422
        assert c.post("/api/auth/signup", json={"email": "a@b.com", "password": "Strong@Pass1"}).status_code == 200
        assert c.post("/api/auth/signup", json={"email": "a@b.com", "password": "Strong@Pass1"}).status_code == 409
        tok = c.post("/api/auth/login", json={"email": "admin@brightloop.com", "password": "Admin@12345"}).json()["token"]
        H = {"Authorization": "Bearer " + tok}
        cust = c.post("/api/auth/login", json={"email": "a@b.com", "password": "Strong@Pass1"}).json()
        CH = {"Authorization": "Bearer " + cust["token"]}
        # customer cannot create discounts or staff
        assert c.post("/api/discounts", json={"name": "x", "value": 5}, headers=CH).status_code == 403
        assert c.post("/api/staff", json={"email": "s@b.com", "password": "Staff@Pass12"}, headers=CH).status_code == 403
        assert c.post("/api/staff", json={"email": "s@b.com", "password": "Staff@Pass12"}, headers=H).status_code == 200
        # subscription lifecycle
        cid = cust["user"]["customer_id"]
        plan = c.get("/api/plans", headers=H).json()["items"]
        monthly = [p for p in plan if p["name"] == "Business Monthly"][0]
        prod = c.get("/api/products", headers=H).json()["items"]
        crm = [p for p in prod if p["name"] == "Brightloop CRM"][0]
        var = c.get("/api/variants?product_id=%d" % crm["id"], headers=H).json()["items"]
        odoo = [v for v in var if v["value"] == "Odoo"][0]
        s = c.post("/api/subscriptions", headers=H, json={"customer_id": cid, "plan_id": monthly["id"],
              "start_date": str(date.today()), "lines": [{"product_id": crm["id"], "variant_id": odoo["id"], "quantity": 5}]}).json()
        assert s["lines"][0]["unit_price"] == 1560  # 1000 + 560 Odoo variant
        for _ in range(3): c.post(f"/api/subscriptions/{s['id']}/advance", headers=H)
        assert c.get(f"/api/subscriptions/{s['id']}", headers=H).json()["status"] == "active"
        # billing: run twice -> exactly one invoice
        r1 = c.post("/api/billing/run", headers=H).json(); r2 = c.post("/api/billing/run", headers=H).json()
        assert r1["invoices_created"] == 1 and r2["invoices_created"] == 0
        inv = c.get("/api/invoices", headers=H).json()["items"][0]
        # 5 x 1560 = 7800, 10% volume discount = 780, tax 18% of 7020 = 1263.6, total 8283.6
        assert inv["total"] == 8283.6, inv
        c.post(f"/api/invoices/{inv['id']}/confirm", headers=H)
        assert c.post("/api/payments", headers=H, json={"invoice_id": inv["id"], "method": "bank", "amount": 283.6}).status_code == 200
        assert c.get("/api/invoices/%d" % inv["id"], headers=H).json()["status"] == "confirmed"
        c.post("/api/payments", headers=H, json={"invoice_id": inv["id"], "method": "card", "amount": 8000})
        assert c.get("/api/invoices/%d" % inv["id"], headers=H).json()["status"] == "paid"
        # customer sees only own data
        assert c.get("/api/invoices", headers=CH).json()["total"] == 1
        # customers must not see margin data; staff/admin still do; health check works
        cp = c.get("/api/products", headers=CH).json()["items"][0]
        assert "cost_price" not in cp and "notes" not in cp and "sales_price" in cp
        assert "cost_price" not in c.get("/api/products/%d" % crm["id"], headers=CH).json()
        assert "cost_price" in c.get("/api/products", headers=H).json()["items"][0]
        assert c.get("/health").json() == {"status": "ok"}
        sm = c.get("/api/reports/summary", headers=H).json()
        assert sm["active_subscriptions"] == 1 and sm["revenue_collected"] == 8283.6 and sm["outstanding"] == 0
        # forgot password
        assert c.post("/api/auth/forgot-password", json={"email": "a@b.com"}).status_code == 200
