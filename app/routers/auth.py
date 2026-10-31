import os, re, secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from ..database import get_db
from ..deps import current_user, roles
from ..mail import send_email
from ..models import User, Customer, ResetToken
from ..security import hash_pw, verify_pw, password_error, make_token

router = APIRouter(prefix="/api", tags=["auth"])
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def _create_user(db, email, password, name, role):
    email = (email or "").strip().lower()
    if not EMAIL.match(email): raise HTTPException(422, "Enter a valid email address")
    err = password_error(password or "")
    if err: raise HTTPException(422, err)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists")
    u = User(email=email, name=name or "", password_hash=hash_pw(password), role=role)
    db.add(u); db.flush()
    return u


def _me(db, u):
    c = db.query(Customer).filter(Customer.user_id == u.id).first()
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "customer_id": c.id if c else None}


@router.post("/auth/signup")
def signup(body: dict, db=Depends(get_db)):
    u = _create_user(db, body.get("email"), body.get("password"), body.get("name"), "customer")
    db.add(Customer(user_id=u.id, name=u.name or u.email, email=u.email))
    db.commit()
    return {"token": make_token(u.id, u.role), "user": _me(db, u)}


@router.post("/auth/login")
def login(body: dict, db=Depends(get_db)):
    u = db.query(User).filter(User.email == (body.get("email") or "").strip().lower()).first()
    if not u or not verify_pw(body.get("password") or "", u.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    return {"token": make_token(u.id, u.role), "user": _me(db, u)}


@router.post("/auth/forgot-password")
def forgot(body: dict, db=Depends(get_db)):
    u = db.query(User).filter(User.email == (body.get("email") or "").strip().lower()).first()
    if u:
        t = secrets.token_urlsafe(32)
        db.add(ResetToken(user_id=u.id, token=t, expires_at=datetime.utcnow() + timedelta(hours=1)))
        db.commit()
        send_email(u.email, "Reset your Brightloop password",
                   f"Use this link within 1 hour to set a new password:\n{BASE_URL}/#reset={t}")
    return {"ok": True, "message": "If that email is registered, a reset link has been sent."}


@router.post("/auth/reset-password")
def reset(body: dict, db=Depends(get_db)):
    t = db.query(ResetToken).filter(ResetToken.token == body.get("token")).first()
    if not t or t.used or t.expires_at < datetime.utcnow():
        raise HTTPException(400, "This reset link is invalid or has expired")
    err = password_error(body.get("password") or "")
    if err: raise HTTPException(422, err)
    db.get(User, t.user_id).password_hash = hash_pw(body["password"])
    t.used = True
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(u=Depends(current_user), db=Depends(get_db)):
    return _me(db, u)


@router.post("/staff")
def add_staff(body: dict, db=Depends(get_db), admin=Depends(roles("admin"))):
    u = _create_user(db, body.get("email"), body.get("password"), body.get("name"), "staff")
    db.commit()
    return {"id": u.id, "email": u.email, "role": u.role}


@router.get("/staff")
def list_staff(db=Depends(get_db), admin=Depends(roles("admin"))):
    return {"items": [{"id": u.id, "email": u.email, "name": u.name, "role": u.role}
                      for u in db.query(User).filter(User.role.in_(["staff", "admin"])).all()]}
