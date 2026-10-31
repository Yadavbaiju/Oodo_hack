import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(IntegrityError)
async def integrity(request: Request, exc: IntegrityError):
    return JSONResponse(status_code=400, content={"detail": "That record conflicts with existing data or is missing a required value"})


for r in (auth.router, subscriptions.router, invoices.router, reports.router):
    app.include_router(r)

app.include_router(crud_router(Customer, "customers", read=STAFF, write=STAFF))
app.include_router(crud_router(Tax, "taxes", read=STAFF, write=("admin",)))
app.include_router(crud_router(Product, "products", write=("admin",)))
app.include_router(crud_router(Variant, "variants", write=("admin",), filters=("product_id",)))
app.include_router(crud_router(Plan, "plans", write=("admin",)))
app.include_router(crud_router(QuotationTemplate, "quotation-templates", read=STAFF, write=STAFF))
app.include_router(crud_router(TemplateLine, "template-lines", read=STAFF, write=STAFF, filters=("template_id",)))
app.include_router(crud_router(Discount, "discounts", read=STAFF, write=("admin",)))  # only admin creates discounts

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "frontend"), html=True), name="ui")
