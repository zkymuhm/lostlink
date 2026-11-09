"""WBS 4.2 (pelaporan barang) dan 4.3 (pencarian, filter, detail & status)."""
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import matching
from ..auth import current_user
from ..config import FOTO_EXT, MAX_FOTO_MB, UPLOAD_DIR
from ..database import get_db
from ..models import JENIS, KATEGORI, Item, Match, User, Verification
from ..templating import templates

router = APIRouter()


def _form_ctx(**kw):
    base = {"kategori_list": KATEGORI, "errors": [], "form": {}, "aktif": "Lapor barang"}
    base.update(kw)
    return base


@router.get("/lapor")
def lapor_form(request: Request, jenis: str = "hilang", user: User = Depends(current_user)):
    jenis = jenis if jenis in JENIS else "hilang"
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    return templates.TemplateResponse(request, "lapor.html", _form_ctx(user=user, form={"jenis": jenis, "waktu": now}))


@router.post("/laporan")
async def kirim_laporan(
    request: Request,
    jenis: str = Form(""),
    kategori: str = Form(""),
    deskripsi: str = Form(""),
    ciri_khusus: str = Form(""),
    lokasi: str = Form(""),
    waktu: str = Form(""),
    foto: UploadFile | None = File(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    form = {"jenis": jenis, "kategori": kategori, "deskripsi": deskripsi.strip(), "ciri_khusus": ciri_khusus.strip(),
            "lokasi": lokasi.strip(), "waktu": waktu}
    errors = []
    if jenis not in JENIS:
        errors.append("Pilih jenis laporan: barang hilang atau barang temuan.")
    if kategori not in KATEGORI:
        errors.append("Pilih kategori barang.")
    if len(form["deskripsi"]) < 5:
        errors.append("Ciri-ciri umum wajib diisi (minimal 5 karakter).")
    if len(form["ciri_khusus"]) < 3:
        errors.append("Ciri khusus (rahasia) wajib diisi; dipakai untuk verifikasi pemilik.")
    if not form["lokasi"]:
        errors.append("Lokasi wajib diisi.")
    try:
        waktu_dt = datetime.fromisoformat(waktu)
        if waktu_dt > datetime.now() + timedelta(minutes=5):
            errors.append("Waktu kejadian tidak boleh di masa depan.")
    except ValueError:
        waktu_dt = None
        errors.append("Isi perkiraan waktu kejadian.")

    data = await foto.read() if foto and foto.filename else b""
    ext = Path(foto.filename).suffix.lower() if foto and foto.filename else ""
    if not data:
        errors.append("Unggah satu foto barang.")
    elif ext not in FOTO_EXT:
        errors.append("Format foto harus JPG, PNG, WEBP, atau HEIC.")
    elif len(data) > MAX_FOTO_MB * 1024 * 1024:
        errors.append(f"Ukuran foto maksimal {MAX_FOTO_MB} MB.")

    path = None
    if not errors:
        tmp = UPLOAD_DIR / f"tmp_{uuid.uuid4().hex}{ext}"
        tmp.write_bytes(data)
        try:
            img = matching.buka(tmp)
            img.thumbnail((1600, 1600))  # hemat penyimpanan; ekstraksi memakai 224 px
            path = UPLOAD_DIR / f"{uuid.uuid4().hex}.jpg"  # nama acak (laporan M3)
            img.save(path, "JPEG", quality=88)
        except Exception:  # noqa: BLE001
            errors.append("File yang diunggah bukan foto yang valid.")
        finally:
            tmp.unlink(missing_ok=True)

    if errors:
        return templates.TemplateResponse(request, "lapor.html", _form_ctx(user=user, form=form, errors=errors), status_code=400)

    t0 = time.perf_counter()
    vektor = matching.ke_bytes(matching.ekstrak(path))
    item = Item(
        user_id=user.id, jenis=jenis, kategori=kategori, deskripsi=form["deskripsi"], ciri_khusus=form["ciri_khusus"],
        lokasi=form["lokasi"], waktu_kejadian=waktu_dt, path_foto=path.name, vektor_fitur=vektor,
        status="Hilang" if jenis == "hilang" else "Ditemukan",
    )
    db.add(item)
    db.commit()
    request.session["flash"] = f"Laporan tersimpan. Foto diproses dalam {time.perf_counter() - t0:.2f} detik."
    return RedirectResponse(f"/rekomendasi/{item.id}" if jenis == "hilang" else f"/laporan/{item.id}", status_code=303)


@router.get("/laporan")
def cari(
    request: Request,
    q: str = "",
    kategori: str = "",
    lokasi: str = "",
    jenis: str = "",
    dari: str = "",
    sampai: str = "",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Item)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Item.deskripsi.ilike(like), Item.kategori.ilike(like), Item.lokasi.ilike(like)))
    if kategori in KATEGORI:
        stmt = stmt.where(Item.kategori == kategori)
    if lokasi.strip():
        stmt = stmt.where(Item.lokasi.ilike(f"%{lokasi.strip()}%"))
    if jenis in JENIS:
        stmt = stmt.where(Item.jenis == jenis)
    try:
        if dari:
            stmt = stmt.where(Item.waktu_kejadian >= datetime.combine(date.fromisoformat(dari), datetime.min.time()))
        if sampai:
            stmt = stmt.where(Item.waktu_kejadian < datetime.combine(date.fromisoformat(sampai), datetime.min.time()) + timedelta(days=1))
    except ValueError:
        pass
    items = db.scalars(stmt.order_by(Item.waktu_kejadian.desc())).all()
    filt = {"q": q, "kategori": kategori, "lokasi": lokasi, "jenis": jenis, "dari": dari, "sampai": sampai}
    return templates.TemplateResponse(request, "cari.html", {"user": user, "items": items, "f": filt,
                                                             "kategori_list": KATEGORI, "aktif": "Beranda"})


@router.get("/saya")
def laporan_saya(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(Item).where(Item.user_id == user.id).order_by(Item.dibuat_pada.desc())).all()
    return templates.TemplateResponse(request, "saya.html", {"user": user, "items": items, "aktif": "Status laporan"})


def riwayat(db: Session, item: Item) -> list[tuple[datetime, str]]:
    rows = [(item.dibuat_pada, f"Laporan barang {item.jenis} dibuat")]
    kolom = Match.lost_item_id if item.jenis == "hilang" else Match.found_item_id
    q = select(Verification, Match).join(Match, Verification.match_id == Match.id).where(kolom == item.id)
    for v, m in db.execute(q.order_by(Verification.id)).all():
        rows.append((m.dibuat_pada, f"Kecocokan ditemukan: skor kemiripan {m.skor * 100:.0f}% (peringkat {m.peringkat})"))
        rows.append((m.dibuat_pada, "Klaim diajukan; jawaban ciri khusus menunggu penilaian admin"))
        if v.keputusan_admin:
            teks = "Admin menyetujui pengembalian" if v.keputusan_admin == "disetujui" else "Admin menolak klaim; status kembali ke status asal"
            rows.append((v.diputuskan_pada, teks))
    return list(reversed(rows))


@router.get("/laporan/{item_id}")
def detail(item_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "Laporan tidak ditemukan.")
    kontak = None  # kontak penemu dibuka ke pemilik setelah admin menyetujui (KF-11)
    if item.jenis == "hilang" and item.user_id == user.id and item.status == "Dikembalikan":
        row = db.execute(
            select(Item, User).join(Match, Match.found_item_id == Item.id).join(Verification, Verification.match_id == Match.id)
            .join(User, User.id == Item.user_id)
            .where(Match.lost_item_id == item.id, Verification.keputusan_admin == "disetujui")
        ).first()
        if row:
            kontak = {"nama": row[1].nama, "no_kontak": row[1].no_kontak, "lokasi": row[0].lokasi}
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "detail.html", {
        "user": user, "item": item, "milik_saya": item.user_id == user.id, "kontak": kontak,
        "riwayat": riwayat(db, item), "flash": flash, "aktif": "Status laporan"})
