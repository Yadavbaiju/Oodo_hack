from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import Date, Float, Integer, Boolean
from .database import get_db
from .deps import roles


def serialize(o):
    out = {}
    for c in o.__table__.columns:
        v = getattr(o, c.name)
        out[c.name] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


def coerce(model, data: dict) -> dict:
    out = {}
    for c in model.__table__.columns:
        if c.primary_key or c.name not in data:
            continue
        v = data[c.name]
        if v in ("", None):
            out[c.name] = None
            continue
        t = c.type
        try:
            if isinstance(t, Date): v = v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
            elif isinstance(t, Boolean): v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")
            elif isinstance(t, Float): v = float(v)
            elif isinstance(t, Integer): v = int(v)
        except ValueError:
            raise HTTPException(422, f"Invalid value for '{c.name}'")
        out[c.name] = v
    return out


import re

NON_NEGATIVE = {"sales_price", "cost_price", "extra_price", "price", "value", "min_purchase", "min_quantity", "usage_limit", "validity_days", "rate"}
CHOICES = {"billing_period": ("daily", "weekly", "monthly", "yearly"), "kind": ("fixed", "percent"), "scope": ("product", "subscription")}


def validate(model, data: dict):
    """Business-rule checks shared by every CRUD endpoint. Raises HTTP 422 with a clear message."""
    for f in NON_NEGATIVE:
        v = data.get(f)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:  # numbers only: Variant.value is text like "Odoo"
            raise HTTPException(422, f"{f.replace('_', ' ').capitalize()} cannot be negative")
    for f, ok in CHOICES.items():
        v = data.get(f)
        if v is not None and v not in ok: raise HTTPException(422, f"{f.replace('_', ' ').capitalize()} must be one of: {', '.join(ok)}")
    if "name" in data and not str(data["name"] or "").strip(): raise HTTPException(422, "Name is required")
    if data.get("min_quantity") is not None and model.__name__ == "Plan" and data["min_quantity"] < 1:
        raise HTTPException(422, "Minimum quantity must be at least 1")
    if data.get("kind") == "percent" and isinstance(data.get("value"), (int, float)) and data["value"] > 100: raise HTTPException(422, "A percentage discount cannot exceed 100")
    if model.__name__ == "Tax" and (data.get("rate") or 0) > 100: raise HTTPException(422, "Tax rate cannot exceed 100%")
    if data.get("start_date") and data.get("end_date") and data["end_date"] < data["start_date"]:
        raise HTTPException(422, "End date cannot be before the start date")
    if data.get("email") and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", data["email"]):
        raise HTTPException(422, "Enter a valid email address")


def serialize_raw(o):
    return {c.name: getattr(o, c.name) for c in o.__table__.columns}


def crud_router(model, prefix, read=("admin", "staff", "customer"), write=("admin",), filters=()):
    r = APIRouter(prefix="/api/" + prefix, tags=[prefix])

    @r.get("")
    def list_items(request: Request, page: int = 1, size: int = 50, db=Depends(get_db), u=Depends(roles(*read))):
        qs = db.query(model)
        for f in filters:
            v = request.query_params.get(f)
            if v:
                qs = qs.filter(getattr(model, f) == coerce(model, {f: v})[f])
        total = qs.count()
        items = qs.order_by(model.id.desc()).offset((max(page, 1) - 1) * size).limit(min(size, 200)).all()
        return {"items": [serialize(i) for i in items], "total": total, "page": page}

    @r.get("/{oid}")
    def get_item(oid: int, db=Depends(get_db), u=Depends(roles(*read))):
        o = db.get(model, oid)
        if not o: raise HTTPException(404, "Not found")
        return serialize(o)

    @r.post("")
    def create(body: dict, db=Depends(get_db), u=Depends(roles(*write))):
        data = {k: v for k, v in coerce(model, body).items() if v is not None}
        validate(model, data)
        o = model(**data)
        db.add(o); db.commit(); db.refresh(o)
        return serialize(o)

    @r.put("/{oid}")
    def update(oid: int, body: dict, db=Depends(get_db), u=Depends(roles(*write))):
        o = db.get(model, oid)
        if not o: raise HTTPException(404, "Not found")
        data = coerce(model, body)
        validate(model, {**serialize_raw(o), **data})
        for k, v in data.items(): setattr(o, k, v)
        db.commit(); db.refresh(o)
        return serialize(o)

    @r.delete("/{oid}")
    def delete(oid: int, db=Depends(get_db), u=Depends(roles(*write))):
        o = db.get(model, oid)
        if not o: raise HTTPException(404, "Not found")
        db.delete(o); db.commit()
        return {"ok": True}

    return r
