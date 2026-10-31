import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from .crud import crud_router
from .database import Base, engine, SessionLocal
from .models import Customer, Tax, Product, Variant, Plan, QuotationTemplate, TemplateLine, Discount
from .routers import auth, subscriptions, invoices, reports
from .seed import seed

STAFF = ("admin", "staff")


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="Brightloop Subscription Management", lifespan=lifespan)
# The UI is served by this same app, so no CORS is needed by default (same-origin only).
# To allow a separately hosted frontend, set e.g. CORS_ORIGINS="https://app.example.com,http://localhost:3000"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])


@app.exception_handler(IntegrityError)
async def integrity(request: Request, exc: IntegrityError):
    return JSONResponse(status_code=400, content={"detail": "That record conflicts with existing data or is missing a required value"})


@app.get("/health", include_in_schema=False)
def health():
    """Liveness + database check for hosting platforms and uptime monitors."""
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}


for r in (auth.router, subscriptions.router, invoices.router, reports.router):
    app.include_router(r)

app.include_router(crud_router(Customer, "customers", read=STAFF, write=STAFF))
app.include_router(crud_router(Tax, "taxes", read=STAFF, write=("admin",)))
# customers can browse products but must not see our cost price or internal notes
app.include_router(crud_router(Product, "products", write=("admin",), hide={"customer": ("cost_price", "notes")}))
app.include_router(crud_router(Variant, "variants", write=("admin",), filters=("product_id",)))
app.include_router(crud_router(Plan, "plans", write=("admin",)))
app.include_router(crud_router(QuotationTemplate, "quotation-templates", read=STAFF, write=STAFF))
app.include_router(crud_router(TemplateLine, "template-lines", read=STAFF, write=STAFF, filters=("template_id",)))
app.include_router(crud_router(Discount, "discounts", read=STAFF, write=("admin",)))  # only admin creates discounts

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "frontend"), html=True), name="ui")
