# Brightloop Subscription Management System

One platform for products, plans, quotes, subscriptions, automated invoicing, payments and revenue reporting.

## Run it (3 commands)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Open http://localhost:8000 (app) or http://localhost:8000/docs (interactive API docs).

## Demo logins (created automatically on first start)
| Role | Email | Password |
|---|---|---|
| Admin | admin@brightloop.com | Admin@12345 |
| Customer | demo@customer.com | Customer@123 |
Admin can add staff from the "Staff" page.

## Tests
`python -m pytest -q` - runs signup rules, roles, variants pricing, billing (no double invoices), discounts, tax, payments, reports.

## Architecture
FastAPI + SQLAlchemy (SQLite by default, set DATABASE_URL for Postgres) + JWT auth + a single-page UI in `frontend/`.
- `app/models.py` all tables - `app/billing.py` invoice engine (period math, discounts, tax)
- `app/routers/` auth, subscriptions, invoices+payments+billing run, reports
- `app/crud.py` role-protected CRUD used for products, plans, taxes, discounts, templates, customers
Emails (reset links, sent invoices) print to the console and `outbox.log`; set `SMTP_HOST/SMTP_USER/SMTP_PASS` to send for real.
