"""Aplikasi FastAPI LOSTLINK. Jalankan: uvicorn app.main:app --reload"""
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .auth import LoginRequired, current_user, require_admin
from .database import Base, engine
from .models import User
from .routers import auth
from .templating import templates

Base.metadata.create_all(bind=engine)

app = FastAPI(title="LOSTLINK")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("LOSTLINK_SECRET", "ganti-dengan-teks-acak-panjang"),
    same_site="lax",
    max_age=60 * 60 * 8,  # sesi 8 jam
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(auth.router)


@app.exception_handler(LoginRequired)
async def to_login(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        request, "error.html", {"kode": exc.status_code, "pesan": exc.detail}, status_code=exc.status_code
    )


@app.get("/")
def beranda(request: Request, user: User = Depends(current_user)):
    if user.peran == "admin":
        return RedirectResponse("/admin/klaim", status_code=303)
    return templates.TemplateResponse(request, "beranda.html", {"user": user, "aktif": "Beranda"})


@app.get("/admin/klaim")
def admin_klaim(request: Request, user: User = Depends(require_admin)):
    # Isi tabel klaim dikerjakan di WBS 4.4; halaman ini sementara membuktikan hak akses admin.
    return templates.TemplateResponse(request, "admin/klaim.html", {"user": user, "aktif": "Persetujuan klaim"})
