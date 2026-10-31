import hashlib, hmac, os, re
from datetime import datetime, timedelta
import jwt

SECRET = os.getenv("SECRET_KEY", "dev-secret-change-me")


def hash_pw(p: str) -> str:
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", p.encode(), salt, 100_000)
    return salt.hex() + "$" + h.hex()


def verify_pw(p: str, stored: str) -> bool:
    salt, h = stored.split("$")
    c = hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), 100_000).hex()
    return hmac.compare_digest(c, h)


def password_error(p: str):
    if len(p) <= 8: return "Password must be more than 8 characters"
    if not re.search(r"[A-Z]", p): return "Password needs an uppercase letter"
    if not re.search(r"[a-z]", p): return "Password needs a lowercase letter"
    if not re.search(r"[^A-Za-z0-9]", p): return "Password needs a special character"
    return None


def make_token(uid: int, role: str) -> str:
    return jwt.encode({"sub": str(uid), "role": role, "exp": datetime.utcnow() + timedelta(hours=12)}, SECRET, algorithm="HS256")
