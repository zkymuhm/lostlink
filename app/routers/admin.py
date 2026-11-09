"""Halaman admin: persetujuan klaim (KF-13), semua laporan dan pengguna (KF-14). Semua butuh peran admin (KNF-04)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..config import UPLOAD_DIR
from ..database import get_db
from ..models import Item, Match, User, Verification
from ..templating import templates

router = APIRouter(prefix="/admin")


def _klaim_rows(db: Session, status: str):
    q = (select(Verification, Match, User).join(Match, Verification.match_id == Match.id)
         .join(User, User.id == Verification.claimant_id))
    q = q.where(Verification.keputusan_admin.is_(None)) if status == "menunggu" else q.where(Verification.keputusan_admin.is_not(None))
    rows = []
    for v, m, u in db.execute(q.order_by(Verification.id.desc())).all():
        rows.append({"v": v, "m": m, "pengklaim": u, "lost": db.get(Item, m.lost_item_id), "found": db.get(Item, m.found_item_id)})
    return rows


@router.get("/klaim")
def daftar_klaim(request: Request, id: int | None = None, status: str = "menunggu",
                 admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = _klaim_rows(db, status)
    pilih = next((r for r in rows if r["v"].id == id), rows[0] if rows else None)
    return templates.TemplateResponse(request, "admin/klaim.html", {
        "user": admin, "rows": rows, "pilih": pilih, "status": status, "aktif": "Persetujuan klaim",
        "flash": request.session.pop("flash", None)})


def _putuskan(db: Session, vid: int, admin: User, setuju: bool) -> Verification:
    v = db.get(Verification, vid)
    if v is None or v.keputusan_admin:
        raise HTTPException(404, "Klaim tidak ditemukan atau sudah diputuskan.")
    m = db.get(Match, v.match_id)
    lost, found = db.get(Item, m.lost_item_id), db.get(Item, m.found_item_id)
    v.keputusan_admin = "disetujui" if setuju else "ditolak"
    v.hasil = "cocok" if setuju else "tidak cocok"
    v.admin_id, v.diputuskan_pada = admin.id, datetime.now()
    if setuju:
        lost.status = found.status = "Dikembalikan"
    else:  # status kembali ke status asal (laporan M3, endpoint 15)
        lost.status, found.status = "Hilang", "Ditemukan"
    db.commit()
    return v


@router.post("/klaim/{vid}/setujui")
def setujui(vid: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    _putuskan(db, vid, admin, True)
    request.session["flash"] = "Pengembalian disetujui. Kontak penemu kini terbuka untuk pemilik."
    return RedirectResponse("/admin/klaim", status_code=303)


@router.post("/klaim/{vid}/tolak")
def tolak(vid: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    _putuskan(db, vid, admin, False)
    request.session["flash"] = "Klaim ditolak. Status barang dikembalikan ke status asal."
    return RedirectResponse("/admin/klaim", status_code=303)


@router.get("/laporan")
def semua_laporan(request: Request, q: str = "", jenis: str = "", status: str = "",
                  admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(Item, User).join(User, User.id == Item.user_id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Item.deskripsi.ilike(like), User.nama.ilike(like), Item.lokasi.ilike(like)))
    if jenis:
        stmt = stmt.where(Item.jenis == jenis)
    if status:
        stmt = stmt.where(Item.status == status)
    rows = db.execute(stmt.order_by(Item.dibuat_pada.desc())).all()
    total = db.scalar(select(func.count(Item.id)))
    return templates.TemplateResponse(request, "admin/laporan.html", {
        "user": admin, "rows": rows, "total": total, "f": {"q": q, "jenis": jenis, "status": status},
        "aktif": "Semua laporan", "flash": request.session.pop("flash", None)})


@router.post("/laporan/{item_id}/hapus")
def hapus_laporan(item_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "Laporan tidak ditemukan.")
    mids = select(Match.id).where(or_(Match.lost_item_id == item.id, Match.found_item_id == item.id))
    db.execute(delete(Verification).where(Verification.match_id.in_(mids)))
    db.execute(delete(Match).where(or_(Match.lost_item_id == item.id, Match.found_item_id == item.id)))
    (UPLOAD_DIR / item.path_foto).unlink(missing_ok=True)
    db.delete(item)
    db.commit()
    request.session["flash"] = "Laporan dihapus."
    return RedirectResponse("/admin/laporan", status_code=303)


@router.get("/pengguna")
def pengguna(request: Request, q: str = "", admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(User, func.count(Item.id)).outerjoin(Item, Item.user_id == User.id).group_by(User.id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.nama.ilike(like), User.email.ilike(like)))
    rows = db.execute(stmt.order_by(User.dibuat_pada)).all()
    return templates.TemplateResponse(request, "admin/pengguna.html", {
        "user": admin, "rows": rows, "q": q, "aktif": "Pengguna", "flash": request.session.pop("flash", None)})


@router.post("/pengguna/{uid}/nonaktif")
def nonaktif(uid: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None or u.peran == "admin":
        raise HTTPException(400, "Akun admin tidak dapat dinonaktifkan.")
    u.aktif = not u.aktif  # tombol yang sama untuk menonaktifkan / mengaktifkan kembali
    db.commit()
    request.session["flash"] = f"Akun {u.nama} {'diaktifkan kembali' if u.aktif else 'dinonaktifkan'}."
    return RedirectResponse("/admin/pengguna", status_code=303)
