"""Checks that the API rejects bad input with a clear 422 message and still accepts good input."""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_validation.db")
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        token = c.post("/api/auth/login", json={"email": "admin@brightloop.com", "password": "Admin@12345"}).json()["token"]
        c.headers.update({"Authorization": "Bearer " + token})
        yield c


# (url, bad body, text that must appear in the error message)
BAD_INPUT = [
    ("/api/products", {"name": "X", "sales_price": -500}, "negative"),
    ("/api/products", {"name": "X", "sales_price": 10, "cost_price": -1}, "negative"),
    ("/api/variants", {"product_id": 1, "attribute": "Brand", "value": "V", "extra_price": -9999}, "negative"),
    ("/api/plans", {"name": "P", "price": 10, "billing_period": "hourly"}, "Billing period"),
    ("/api/plans", {"name": "P", "price": 10, "billing_period": "monthly", "min_quantity": 0}, "Minimum quantity"),
    ("/api/plans", {"name": "P", "price": 10, "billing_period": "monthly", "start_date": "2026-12-01", "end_date": "2026-01-01"}, "End date"),
    ("/api/discounts", {"name": "D", "kind": "percent", "value": 500}, "100"),
    ("/api/discounts", {"name": "D", "kind": "fixed", "value": -50}, "negative"),
    ("/api/discounts", {"name": "D", "kind": "fixed", "value": 5, "start_date": "2026-12-01", "end_date": "2026-01-01"}, "End date"),
    ("/api/taxes", {"name": "T", "rate": 900}, "100"),
    ("/api/customers", {"name": "Z", "email": "notanemail"}, "valid email"),
    ("/api/subscriptions", {"customer_id": 1, "plan_id": 1, "start_date": "2026-11-01", "lines": [{"product_id": 1, "quantity": -3}]}, "greater than"),
    ("/api/subscriptions", {"customer_id": 1, "plan_id": 1, "start_date": "2026-11-01", "expiry_date": "2020-01-01", "lines": []}, "Expiry date"),
]


@pytest.mark.parametrize("url,body,message", BAD_INPUT)
def test_bad_input_is_rejected(admin, url, body, message):
    r = admin.post(url, json=body)
    assert r.status_code == 422, r.text
    assert message.lower() in r.text.lower()


def test_good_input_is_still_accepted(admin):
    assert admin.post("/api/products", json={"name": "Valid product", "sales_price": 100, "cost_price": 40}).status_code == 200
    assert admin.post("/api/discounts", json={"name": "Valid 10%", "kind": "percent", "value": 10}).status_code == 200
    assert admin.post("/api/taxes", json={"name": "VAT 5%", "rate": 5}).status_code == 200
    assert admin.post("/api/customers", json={"name": "Valid Co", "email": "ok@example.com"}).status_code == 200


def test_editing_cannot_bypass_validation(admin):
    pid = admin.post("/api/products", json={"name": "Edit me", "sales_price": 10}).json()["id"]
    assert admin.put(f"/api/products/{pid}", json={"sales_price": -1}).status_code == 422
    assert admin.get(f"/api/products/{pid}").json()["sales_price"] == 10  # unchanged


@pytest.mark.parametrize("password", ["abc", "Abcdef!1", "Abcdefgh1", "abcdefgh1!", "ABCDEFGH1!"])
def test_weak_passwords_are_rejected(admin, password):
    r = admin.post("/api/auth/signup", json={"email": "weak@example.com", "password": password})
    assert r.status_code == 422


def test_nine_character_password_is_accepted(admin):
    r = admin.post("/api/auth/signup", json={"email": "nine@example.com", "password": "Abcdefg1!"})
    assert r.status_code == 200
