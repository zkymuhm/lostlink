"""WBS 4.2 (pelaporan barang) dan 4.3 (pencarian, filter, detail & status)."""
import re
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


TMP_RE = re.compile(r"tmp_[0-9a-f]{32}\.jpg")


def _form_ctx(**kw):
    base = {"kategori_list": KATEGORI, "errors": {}, "form": {}, "aktif": "Lapor",
            "maks_waktu": datetime.now().strftime("%Y-%m-%dT%H:%M"), "maks_mb": MAX_FOTO_MB}
    base.update(kw)
    return base


def _potong(img, potong: str):
    """Potong foto sesuai kotak dari alat potong di form: "x,y,lebar,tinggi" dalam pecahan 0-1.
    Nilai tidak sah atau kotak terlalu kecil diabaikan (foto dipakai utuh)."""
    try:
        x, y, w, h = (float(v) for v in potong.split(","))
    except ValueError:
        return img
    if not (0 <= x < 1 and 0 <= y < 1 and 0.05 <= w <= 1 and 0.05 <= h <= 1):
        return img
    kiri, atas = int(x * img.width), int(y * img.height)
    kanan, bawah = min(img.width, int((x + w) * img.width)), min(img.height, int((y + h) * img.height))
    if kanan - kiri < 32 or bawah - atas < 32:
        return img
    return img.crop((kiri, atas, kanan, bawah))


def _bersihkan_tmp():
    """Hapus foto sementara dari form yang ditinggalkan (lebih dari 1 hari)."""
    batas = time.time() - 86400
    for f in UPLOAD_DIR.glob("tmp_*.jpg"):
        if f.stat().st_mtime < batas:
            f.unlink(missing_ok=True)


def _judul_default(kategori: str, lokasi: str) -> str:
    lokasi = re.sub(r"^(di|dekat)\s+", "", lokasi.strip(), flags=re.I)  # hindari "di di jalan ..."
    return f"Barang {kategori.lower()} di {lokasi}" if kategori and lokasi else "Barang"


def _baca_waktu(waktu: str, errors: dict) -> datetime:
    """Waktu boleh dikosongkan (dianggap sekarang); hanya masa depan yang ditolak."""
    if not waktu:
        return datetime.now().replace(second=0, microsecond=0)
    try:
        dt = datetime.fromisoformat(waktu)
    except ValueError:
        return datetime.now().replace(second=0, microsecond=0)
    if dt > datetime.now() + timedelta(minutes=5):
        errors["waktu"] = "Waktunya ada di masa depan. Pilih kira-kira kapan terakhir kamu melihat barang itu."
    return dt


@router.get("/lapor")
def lapor_form(request: Request, jenis: str = "hilang", untuk: int | None = None, user: User = Depends(current_user)):
    jenis = jenis if jenis in JENIS else "hilang"
    return templates.TemplateResponse(request, "lapor.html", _form_ctx(user=user, form={"jenis": jenis, "untuk": untuk or ""}))


@router.post("/laporan")
async def kirim_laporan(
    request: Request,
    jenis: str = Form(""),
    kategori: str = Form(""),
    nama: str = Form(""),
    deskripsi: str = Form(""),
    ciri_khusus: str = Form(""),
    lokasi: str = Form(""),
    waktu: str = Form(""),
    foto: UploadFile | None = File(None),
    foto_tmp: str = Form(""),
    untuk: str = Form(""),
    potong: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    form = {"jenis": jenis, "kategori": kategori, "nama": nama.strip()[:60], "deskripsi": deskripsi.strip(), "ciri_khusus": ciri_khusus.strip(),
            "lokasi": lokasi.strip(), "waktu": waktu, "untuk": untuk if untuk.isdigit() else ""}
    _bersihkan_tmp()
    errors: dict[str, str] = {}
    # Wajib hanya: jenis, foto, kategori, lokasi. Detail lain boleh dilengkapi nanti.
    if jenis not in JENIS:
        errors["jenis"] = "Pilih dulu: barangmu hilang, atau kamu menemukan barang."

    # Foto: file baru diutamakan; bila kosong, pakai foto yang sudah terunggah pada percobaan sebelumnya.
    data = await foto.read() if foto and foto.filename else b""
    ext = Path(foto.filename).suffix.lower() if foto and foto.filename else ""
    tmp_path = UPLOAD_DIR / foto_tmp if TMP_RE.fullmatch(foto_tmp or "") else None
    if data:
        if ext not in FOTO_EXT:
            errors["foto"] = f"File \u201c{foto.filename}\u201d bukan format foto yang didukung. Pakai JPG, PNG, WEBP, atau HEIC."
        elif len(data) > MAX_FOTO_MB * 1024 * 1024:
            errors["foto"] = (f"Fotonya {len(data) / 1024 / 1024:.1f} MB, lebih dari batas {MAX_FOTO_MB} MB. "
                              "Coba pilih ulang dari galeri atau kirim versi yang lebih kecil.")
        else:
            raw = UPLOAD_DIR / f"raw_{uuid.uuid4().hex}{ext}"
            raw.write_bytes(data)
            try:
                img = _potong(matching.buka(raw), potong)
                img.thumbnail((1600, 1600))  # hemat penyimpanan; ekstraksi memakai 224 px
                tmp_path = UPLOAD_DIR / f"tmp_{uuid.uuid4().hex}.jpg"
                img.save(tmp_path, "JPEG", quality=88)
            except Exception:  # noqa: BLE001
                errors["foto"] = "File ini sepertinya bukan foto atau rusak. Coba pilih foto lain dari galeri atau kamera."
            finally:
                raw.unlink(missing_ok=True)
    elif tmp_path is None or not tmp_path.exists():
        tmp_path = None
        errors["foto"] = "Fotonya belum ada, yuk unggah satu. Foto membantu kami mencarikan barang yang mirip."
    if "foto" in errors:
        tmp_path = None
    if kategori not in KATEGORI:
        errors["kategori"] = "Pilih kategori yang paling mendekati. Kalau ragu, pilih Lainnya."
    if not form["lokasi"]:
        errors["lokasi"] = "Tulis perkiraan lokasinya, misalnya Stasiun Malang, ruang tunggu."
    if jenis == "temuan" and len(form["ciri_khusus"]) < 3:
        errors["ciri_khusus"] = ("Tulis satu ciri khusus yang hanya diketahui pemiliknya (minimal 3 huruf), "
                                 "supaya barang tidak diklaim orang yang salah.")
    waktu_dt = _baca_waktu(waktu, errors)

    if errors:
        form["foto_tmp"] = tmp_path.name if tmp_path else ""
        return templates.TemplateResponse(request, "lapor.html", _form_ctx(user=user, form=form, errors=errors), status_code=400)

    path = UPLOAD_DIR / f"{uuid.uuid4().hex}.jpg"  # nama acak (laporan M3)
    tmp_path.rename(path)

    t0 = time.perf_counter()
    vektor = matching.ke_bytes(matching.ekstrak(path))
    item = Item(
        user_id=user.id, jenis=jenis, kategori=kategori, nama=form["nama"], deskripsi=form["deskripsi"] or form["nama"] or _judul_default(kategori, form["lokasi"]),
        ciri_khusus=form["ciri_khusus"], lokasi=form["lokasi"], waktu_kejadian=waktu_dt, path_foto=path.name,
        vektor_fitur=vektor, status="Hilang" if jenis == "hilang" else "Ditemukan",
    )
    db.add(item)
    db.commit()
    detik = time.perf_counter() - t0
    if jenis == "hilang" and form["untuk"]:  # datang dari tombol "Ini barangku" -> kembali ke form klaim
        request.session["flash"] = "Laporanmu tersimpan. Sekarang lengkapi bukti kepemilikan untuk mengklaim barang ini."
        return RedirectResponse(f"/barang/{form['untuk']}/klaim?hilang={item.id}", status_code=303)
    if jenis == "hilang":
        request.session["flash"] = f"Laporanmu tersimpan dan langsung dicocokkan ({detik:.1f} detik). Ini barang temuan yang paling mirip."
        return RedirectResponse(f"/rekomendasi/{item.id}", status_code=303)
    request.session["flash"] = "Terima kasih! Barang temuanmu tersimpan dan kini bisa ditemukan pemiliknya."
    return RedirectResponse(f"/laporan/{item.id}", status_code=303)


@router.get("/laporan/{item_id}/ubah")
def ubah_form(item_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(404, "Laporan tidak ditemukan atau bukan milikmu.")
    form = {"kategori": item.kategori, "nama": item.nama or "", "deskripsi": item.deskripsi, "ciri_khusus": item.ciri_khusus, "lokasi": item.lokasi,
            "waktu": item.waktu_kejadian.strftime("%Y-%m-%dT%H:%M")}
    return templates.TemplateResponse(request, "ubah.html", _form_ctx(user=user, item=item, form=form, aktif="Laporanku"))


@router.post("/laporan/{item_id}/ubah")
def ubah(item_id: int, request: Request, kategori: str = Form(""), nama: str = Form(""), deskripsi: str = Form(""), ciri_khusus: str = Form(""),
         lokasi: str = Form(""), waktu: str = Form(""), user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(404, "Laporan tidak ditemukan atau bukan milikmu.")
    form = {"kategori": kategori, "nama": nama.strip()[:60], "deskripsi": deskripsi.strip(), "ciri_khusus": ciri_khusus.strip(), "lokasi": lokasi.strip(), "waktu": waktu}
    errors: dict[str, str] = {}
    if kategori not in KATEGORI:
        errors["kategori"] = "Pilih kategori yang paling mendekati. Kalau ragu, pilih Lainnya."
    if not form["lokasi"]:
        errors["lokasi"] = "Tulis perkiraan lokasinya, misalnya Stasiun Malang, ruang tunggu."
    if item.jenis == "temuan" and len(form["ciri_khusus"]) < 3:
        errors["ciri_khusus"] = "Barang temuan perlu satu ciri khusus (minimal 3 huruf) untuk verifikasi pemilik."
    waktu_dt = _baca_waktu(waktu, errors)
    if errors:
        return templates.TemplateResponse(request, "ubah.html", _form_ctx(user=user, item=item, form=form, errors=errors,
                                                                          aktif="Laporanku"), status_code=400)
    item.kategori, item.lokasi, item.waktu_kejadian = kategori, form["lokasi"], waktu_dt
    item.deskripsi = form["deskripsi"] or _judul_default(kategori, form["lokasi"])
    item.ciri_khusus = form["ciri_khusus"]
    item.nama = form["nama"]
    db.commit()
    request.session["flash"] = "Detail laporan diperbarui."
    return RedirectResponse(f"/laporan/{item.id}", status_code=303)


@router.get("/laporan")
def cari(
    request: Request,
    q: str = "",
    kategori: str = "",
    lokasi: str = "",
    jenis: str = "temuan",
    dari: str = "",
    sampai: str = "",
    selesai: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Menu Cari dipisah dua tab agar tidak tertukar: barang ditemukan (menunggu pemilik, bawaan)
    dan barang yang dicari pemiliknya. Barang yang sudah diproses disembunyikan kecuali selesai=1."""
    jenis = jenis if jenis in JENIS else "temuan"
    stmt = select(Item)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Item.nama.ilike(like), Item.deskripsi.ilike(like), Item.kategori.ilike(like), Item.lokasi.ilike(like)))
    if kategori in KATEGORI:
        stmt = stmt.where(Item.kategori == kategori)
    if lokasi.strip():
        stmt = stmt.where(Item.lokasi.ilike(f"%{lokasi.strip()}%"))
    if not selesai:
        stmt = stmt.where(Item.status.in_(("Hilang", "Ditemukan")))
    try:
        if dari:
            stmt = stmt.where(Item.waktu_kejadian >= datetime.combine(date.fromisoformat(dari), datetime.min.time()))
        if sampai:
            stmt = stmt.where(Item.waktu_kejadian < datetime.combine(date.fromisoformat(sampai), datetime.min.time()) + timedelta(days=1))
    except ValueError:
        pass
    semua = db.scalars(stmt.order_by(Item.waktu_kejadian.desc())).all()
    items = [it for it in semua if it.jenis == jenis]
    jumlah = {j: sum(1 for it in semua if it.jenis == j) for j in JENIS}
    filt = {"q": q, "kategori": kategori, "lokasi": lokasi, "jenis": jenis, "dari": dari, "sampai": sampai, "selesai": selesai}
    return templates.TemplateResponse(request, "cari.html", {"user": user, "items": items, "f": filt, "jumlah": jumlah,
                                                             "kategori_list": KATEGORI, "aktif": "Cari"})


@router.get("/saya")
def laporan_saya(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(Item).where(Item.user_id == user.id).order_by(Item.dibuat_pada.desc())).all()
    return templates.TemplateResponse(request, "saya.html", {"user": user, "items": items, "aktif": "Laporanku"})


def riwayat(db: Session, item: Item) -> list[tuple[datetime, str]]:
    rows = [(item.dibuat_pada, f"Laporan barang {item.jenis} dibuat")]
    kolom = Match.lost_item_id if item.jenis == "hilang" else Match.found_item_id
    q = select(Verification, Match).join(Match, Verification.match_id == Match.id).where(kolom == item.id)
    for v, m in db.execute(q.order_by(Verification.id)).all():
        rows.append((m.dibuat_pada, f"Kecocokan ditemukan: {matching.tingkat(m.skor)[0].lower()}, {matching.persen(m.skor)}% (peringkat {m.peringkat})"))
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
        "riwayat": riwayat(db, item), "flash": flash, "aktif": "Laporanku" if item.user_id == user.id else "Cari"})
