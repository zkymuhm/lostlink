"""WBS 4.1 — registrasi, login, logout berbasis peran."""
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import hash_password, verify_password
from ..database import get_db
from ..models import User
from ..templating import templates

router = APIRouter()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _home_for(user: User) -> str:
    return "/admin/klaim" if user.peran == "admin" else "/"


@router.get("/register")
def register_form(request: Request):
    return templates.TemplateResponse(request, "register.html", {"errors": [], "form": {}})


@router.post("/register")
def register(
    request: Request,
    nama: str = Form(""),
    email: str = Form(""),
    no_kontak: str = Form(""),
    password: str = Form(""),
    password2: str = Form(""),
    setuju: str | None = Form(None),
    db: Session = Depends(get_db),
):
    nama, email, no_kontak = nama.strip(), email.strip().lower(), no_kontak.strip()
    errors = []
    if not nama:
        errors.append("Nama lengkapnya belum diisi.")
    if not EMAIL_RE.match(email):
        errors.append("Format email belum tepat, contohnya nama@email.com.")
    elif db.scalar(select(User).where(User.email == email)):
        errors.append("Email ini sudah terdaftar. Coba masuk saja.")
    if not re.fullmatch(r"[0-9+ ]{8,20}", no_kontak):
        errors.append("Nomor WhatsApp berisi 8–20 angka, contohnya 081234567890.")
    if len(password) < 8:
        errors.append("Kata sandi minimal 8 karakter, ya.")
    if password != password2:
        errors.append("Ulangi kata sandi tidak sama dengan kata sandi di sebelahnya.")
    if not setuju:
        errors.append("Centang persetujuan penggunaan data untuk melanjutkan.")
    if errors:
        form = {"nama": nama, "email": email, "no_kontak": no_kontak}
        return templates.TemplateResponse(request, "register.html", {"errors": errors, "form": form}, status_code=400)

    db.add(User(nama=nama, email=email, no_kontak=no_kontak, password_hash=hash_password(password), peran="pengguna"))
    db.commit()
    return RedirectResponse("/login?daftar=1", status_code=303)


@router.get("/login")
def login_form(request: Request, daftar: int = 0):
    info = "Akunmu sudah jadi. Silakan masuk." if daftar else None
    return templates.TemplateResponse(request, "login.html", {"error": None, "info": info, "email": ""})


@router.post("/login")
def login(request: Request, email: str = Form(""), password: str = Form(""), db: Session = Depends(get_db)):
    email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    error = None
    if user is None or not verify_password(password, user.password_hash):
        error = "Email atau kata sandinya belum cocok. Coba periksa lagi."
    elif not user.aktif:
        error = "Akun ini sedang dinonaktifkan admin. Hubungi admin bila menurutmu ini keliru."
    if error:
        return templates.TemplateResponse(request, "login.html", {"error": error, "info": None, "email": email}, status_code=401)

    request.session.clear()
    request.session.update({"user_id": user.id, "peran": user.peran})
    return RedirectResponse(_home_for(user), status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
