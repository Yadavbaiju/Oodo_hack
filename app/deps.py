import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from .database import get_db
from .models import User, Customer
from .security import SECRET

bearer = HTTPBearer(auto_error=False)


def current_user(cred=Depends(bearer), db=Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(401, "Not authenticated")
    try:
        data = jwt.decode(cred.credentials, SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    u = db.get(User, int(data["sub"]))
    if not u:
        raise HTTPException(401, "User not found")
    return u


def roles(*allowed):
    def dep(u: User = Depends(current_user)):
        if u.role not in allowed:
            raise HTTPException(403, "You do not have access to this action")
        return u
    return dep


def my_customer_id(db, u: User):
    c = db.query(Customer).filter(Customer.user_id == u.id).first()
    return c.id if c else -1
