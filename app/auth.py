"""Hash kata sandi (bcrypt) dan pengecekan sesi + peran (KF-01, KF-02, KNF-04)."""
from fastapi import Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd.verify(plain, hashed)


class LoginRequired(Exception):
    """Dilempar bila belum login; main.py mengubahnya menjadi redirect ke /login."""


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get("user_id")
    user = db.get(User, uid) if uid else None
    if user is None or not user.aktif:
        request.session.clear()
        raise LoginRequired()
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.peran != "admin":
        raise HTTPException(status_code=403, detail="Halaman ini khusus admin.")
    return user
