"""Aplikasi FastAPI LOSTLINK. Jalankan: uvicorn app.main:app --reload"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import matching
from .auth import LoginRequired, current_user
from .config import UPLOAD_DIR
from .database import Base, engine, get_db
from .models import Item, User
from .routers import admin, auth, klaim, laporan
from .templating import templates

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    matching.siapkan_model()  # muat ResNet18 sekali saat server dinyalakan
    yield


app = FastAPI(title="LOSTLINK", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("LOSTLINK_SECRET", "ganti-dengan-teks-acak-panjang"),
    same_site="lax",
    max_age=60 * 60 * 8,  # sesi 8 jam
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.mount("/foto", StaticFiles(directory=str(UPLOAD_DIR)), name="foto")
app.include_router(auth.router)
app.include_router(laporan.router)
app.include_router(klaim.router)
app.include_router(admin.router)


@app.exception_handler(LoginRequired)
async def to_login(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        request, "error.html", {"kode": exc.status_code, "pesan": exc.detail}, status_code=exc.status_code
    )


@app.get("/")
def beranda(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.peran == "admin":
        return RedirectResponse("/admin/klaim", status_code=303)
    saya = db.scalars(select(Item).where(Item.user_id == user.id).order_by(Item.dibuat_pada.desc()).limit(5)).all()
    temuan = db.scalars(select(Item).where(Item.jenis == "temuan").order_by(Item.dibuat_pada.desc()).limit(4)).all()
    return templates.TemplateResponse(request, "beranda.html", {
        "user": user, "saya": saya, "temuan": temuan, "aktif": "Beranda",
        "kategori_list": ("Tas", "Dompet", "Ponsel", "Kunci", "Lainnya")})
