"""WBS 5.3 (rekomendasi top-5) dan 4.4 (klaim + verifikasi ciri khusus)."""
import time
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import foto as foto_util
from .. import matching
from ..auth import current_user
from ..config import UPLOAD_DIR
from ..database import get_db
from ..models import Item, Match, User, Verification
from ..templating import templates

router = APIRouter()
TOP_K = 5


@router.get("/rekomendasi")
def rekomendasi_terbaru(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.scalars(select(Item).where(Item.user_id == user.id, Item.jenis == "hilang").order_by(Item.dibuat_pada.desc())).first()
    if item:
        return RedirectResponse(f"/rekomendasi/{item.id}", status_code=303)
    # Belum punya laporan hilang: jelaskan dulu fungsi Rekomendasi, jangan langsung dilempar ke form
    return templates.TemplateResponse(request, "rekomendasi_kosong.html", {"user": user, "aktif": "Laporanku"})


def _laporan_hilang_milik(db: Session, item_id: int, user: User) -> Item:
    item = db.get(Item, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(404, "Laporan tidak ditemukan atau bukan milikmu.")
    return item


def _urutan(db: Session, item: Item):
    """Semua barang temuan yang belum diklaim, diurutkan dari yang paling mirip.
    Fotomu dibandingkan dengan SEMUA barang temuan. Data lain (kategori, waktu, lokasi, nama) hanya menambah
    skor lewat matching.skor_gabungan, tidak menyaring (keputusan 10 Nov 2026).
    Kembalian: pool {id: Item}, foto {id: skor foto}, gabung {id: (skor, alasan)}, urut [id ...]."""
    pool = {it.id: it for it in db.scalars(select(Item).where(Item.jenis == "temuan", Item.status == "Ditemukan"))}
    foto = matching.skor_foto_semua(item.vektor_fitur, [(i, it.vektor_fitur) for i, it in pool.items()])
    gabung = {fid: matching.skor_gabungan(item, pool[fid], s) for fid, s in foto.items()}
    urut = sorted(gabung, key=lambda fid: -gabung[fid][0])
    return pool, foto, gabung, urut


def _layak(gabung: dict, urut: list) -> list:
    """Barang yang cukup mirip untuk ditampilkan (di atas BATAS_TAMPIL)."""
    return [fid for fid in urut if matching.persen(gabung[fid][0]) >= matching.BATAS_TAMPIL]


@router.get("/rekomendasi/{item_id}")
def rekomendasi(item_id: int, request: Request, dekat: int = 0, n: int = 10, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    item = _laporan_hilang_milik(db, item_id, user)
    if item.jenis != "hilang":
        return RedirectResponse(f"/laporan/{item.id}", status_code=303)

    t0 = time.perf_counter()
    pool, foto, gabung, urut = _urutan(db, item)
    layak = _layak(gabung, urut)
    durasi = time.perf_counter() - t0
    n = max(10, min(n, 500))
    # Yang tampil: semua barang yang cukup mirip, dari paling mirip, 10 per halaman ("Tampilkan lagi").
    # Barang yang tidak mirip tidak ditampilkan; dekat=1 menampilkan 5 terdekat bila tidak ada yang cukup mirip.
    tampil_ids = urut[:TOP_K] if dekat else layak[:n]
    peringkat = {fid: i for i, fid in enumerate(urut, start=1)}

    # Simpan ke tabel matches: top-5 (dasar uji akurasi T3) ditambah yang sedang tampil (agar bisa diklaim).
    # Pasangan (hilang, temuan) yang sama memakai baris yang sama agar match_id stabil; baris lain dihapus
    # kecuali sudah pernah diklaim.
    simpan = list(dict.fromkeys(urut[:TOP_K] + tampil_ids))
    lama = {m.found_item_id: m for m in db.scalars(select(Match).where(Match.lost_item_id == item.id))}
    diklaim = set(db.scalars(select(Verification.match_id)))
    for fid, m in lama.items():
        if fid not in simpan and m.id not in diklaim:
            db.delete(m)
    baris = {}
    for fid in simpan:
        m = lama.get(fid)
        if m is None:
            m = Match(lost_item_id=item.id, found_item_id=fid, skor=foto[fid], peringkat=peringkat[fid])
            db.add(m)
            db.flush()
        else:
            m.skor, m.peringkat = foto[fid], peringkat[fid]
        baris[fid] = m
    db.commit()
    tampil = [{"match": baris[fid], "item": pool[fid], "skor": gabung[fid][0], "skor_foto": foto[fid],
               "alasan": gabung[fid][1], "rank": peringkat[fid]} for fid in tampil_ids]

    pending = db.scalars(select(Verification).join(Match).where(Match.lost_item_id == item.id, Verification.keputusan_admin.is_(None))).first()
    pilih = request.query_params.get("klaim")
    pilih_k = next((k for k in tampil if str(k["match"].id) == pilih), None)
    return templates.TemplateResponse(request, "rekomendasi.html", {
        "user": user, "item": item, "kandidat": urut[:TOP_K], "durasi": durasi, "pending": pending, "jumlah": len(foto),
        "tampil": tampil, "dekat": dekat, "layak": len(layak), "n": n, "lebih": max(0, len(layak) - n),
        "tersembunyi": len(urut) - len(layak),
        "pilih": pilih_k, "error": request.session.pop("klaim_error", None), "flash": request.session.pop("flash", None),
        "aktif": "Laporanku"})


@router.get("/rekomendasi/{item_id}/banding/{match_id}")
def banding(item_id: int, match_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Halaman pembanding: foto barangmu dan foto barang temuan berdampingan, lalu klaim dari sini."""
    item = _laporan_hilang_milik(db, item_id, user)
    m = db.get(Match, match_id)
    if m is None or m.lost_item_id != item.id:
        raise HTTPException(404, "Barang rekomendasi tidak ditemukan. Buka lagi halaman rekomendasi.")
    found = db.get(Item, m.found_item_id)
    if found is None:
        raise HTTPException(404, "Barang temuan sudah dihapus.")
    skor_foto = matching.skor_foto_semua(item.vektor_fitur, [(found.id, found.vektor_fitur)]).get(found.id, m.skor)
    skor, alasan = matching.skor_gabungan(item, found, skor_foto)

    # sebelum/berikutnya di antara barang yang tampil di rekomendasi
    _, _, gabung, urut = _urutan(db, item)
    daftar = _layak(gabung, urut) or urut[:TOP_K]
    match_of = {x.found_item_id: x.id for x in db.scalars(select(Match).where(Match.lost_item_id == item.id))}
    nav = {}
    if found.id in daftar:
        i = daftar.index(found.id)
        for kunci, j in (("sebelum", i - 1), ("berikut", i + 1)):
            if 0 <= j < len(daftar) and daftar[j] in match_of:
                nav[kunci] = match_of[daftar[j]]
        nav["posisi"], nav["total"] = i + 1, len(daftar)
    pending = db.scalars(select(Verification).join(Match).where(Match.lost_item_id == item.id, Verification.keputusan_admin.is_(None))).first()
    return templates.TemplateResponse(request, "banding.html", {
        "user": user, "item": item, "found": found, "match": m, "skor": skor, "skor_foto": skor_foto, "alasan": alasan,
        "nav": nav, "pending": pending, "buka_klaim": request.query_params.get("klaim") == "1",
        "error": request.session.pop("klaim_error", None), "aktif": "Laporanku"})


async def _buat_klaim(db: Session, user: User, m: Match, lost: Item, found: Item, jawaban_ciri: str, keterangan: str,
                     bukti: UploadFile | None) -> dict[str, str]:
    """Simpan klaim beserta buktinya. Mengembalikan galat per kolom (kosong bila berhasil)."""
    errors: dict[str, str] = {}
    if len(jawaban_ciri.strip()) < 3:
        errors["jawaban_ciri"] = "Tulis satu ciri khusus yang hanya kamu tahu dari barangmu (minimal 3 huruf)."
    nama_bukti, galat_foto = await foto_util.simpan(bukti, awalan="bukti_")
    if galat_foto:
        errors["bukti_foto"] = galat_foto
    if errors:
        if nama_bukti:
            (UPLOAD_DIR / nama_bukti).unlink(missing_ok=True)
        return errors
    db.add(Verification(match_id=m.id, claimant_id=user.id, jawaban_ciri=jawaban_ciri.strip(),
                        keterangan=keterangan.strip() or None, bukti_foto=nama_bukti))
    lost.status = "Diverifikasi"
    found.status = "Diverifikasi"
    db.commit()
    return {}


@router.post("/klaim")
async def ajukan_klaim(request: Request, match_id: int = Form(...), jawaban_ciri: str = Form(""), keterangan: str = Form(""),
                       bukti_foto: UploadFile | None = File(None), asal: str = Form(""),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(Match, match_id)
    lost = db.get(Item, m.lost_item_id) if m else None
    if m is None or lost is None or lost.user_id != user.id:
        raise HTTPException(404, "Kecocokan tidak ditemukan.")
    found = db.get(Item, m.found_item_id)
    if lost.status != "Hilang" or found is None or found.status != "Ditemukan":
        raise HTTPException(409, "Barang ini sudah dalam proses verifikasi atau sudah dikembalikan.")
    errors = await _buat_klaim(db, user, m, lost, found, jawaban_ciri, keterangan, bukti_foto)
    if errors:
        request.session["klaim_error"] = " ".join(errors.values())
        if asal == "banding":
            return RedirectResponse(f"/rekomendasi/{lost.id}/banding/{m.id}?klaim=1#klaim", status_code=303)
        return RedirectResponse(f"/rekomendasi/{lost.id}?klaim={m.id}#klaim", status_code=303)
    request.session["flash"] = "Klaim terkirim. Admin biasanya memeriksa dalam 1×24 jam; pantau statusnya di halaman ini."
    return RedirectResponse(f"/laporan/{lost.id}", status_code=303)


# --- Klaim langsung dari menu Cari / detail barang temuan ("Ini barangku") ---------------------------

def _barang_temuan(db: Session, found_id: int, user: User) -> Item:
    found = db.get(Item, found_id)
    if found is None or found.jenis != "temuan":
        raise HTTPException(404, "Barang temuan tidak ditemukan.")
    if found.user_id == user.id:
        raise HTTPException(400, "Ini laporan barang temuanmu sendiri.")
    if found.status != "Ditemukan":
        raise HTTPException(409, "Barang ini sedang diverifikasi atau sudah dikembalikan ke pemiliknya.")
    return found


def _urut_kemiripan(milik: list[Item], found: Item) -> list[tuple[Item, float]]:
    """Laporan hilang milik pengguna, diurutkan dari yang fotonya paling mirip dengan barang temuan."""
    skor = matching.skor_foto_semua(found.vektor_fitur, [(it.id, it.vektor_fitur) for it in milik])
    return sorted(((it, skor.get(it.id, -1.0)) for it in milik), key=lambda x: -x[1])


def _laporan_hilang_saya(db: Session, user: User) -> list[Item]:
    return list(db.scalars(select(Item).where(Item.user_id == user.id, Item.jenis == "hilang", Item.status == "Hilang")
                           .order_by(Item.dibuat_pada.desc())))


@router.get("/barang/{found_id}/klaim")
def klaim_form(found_id: int, request: Request, hilang: int | None = None, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    found = _barang_temuan(db, found_id, user)
    milik = _urut_kemiripan(_laporan_hilang_saya(db, user), found)
    if hilang is not None:
        pilihan = hilang
    elif milik and matching.persen(milik[0][1]) >= matching.BATAS_TINGGI:
        pilihan = milik[0][0].id  # hanya dipilih otomatis bila fotonya memang mirip
    else:
        pilihan = None if milik else 0
    return templates.TemplateResponse(request, "klaim.html", {
        "user": user, "found": found, "milik": milik, "form": {"hilang": pilihan},
        "errors": {}, "aktif": "Cari", "flash": request.session.pop("flash", None)})


@router.post("/barang/{found_id}/klaim")
async def klaim_kirim(found_id: int, request: Request, hilang_id: str = Form(""), jawaban_ciri: str = Form(""),
                      keterangan: str = Form(""), lokasi: str = Form(""), nama: str = Form(""),
                      foto_pemilik: UploadFile | None = File(None), potong: str = Form(""),
                      bukti_foto: UploadFile | None = File(None),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Klaim satu halaman dari menu Cari. hilang_id = 0 berarti belum punya laporan hilang:
    laporan hilang dibuat otomatis dari foto dan lokasi di form ini, lalu klaim langsung diajukan."""
    found = _barang_temuan(db, found_id, user)
    milik_list = _laporan_hilang_saya(db, user)
    milik = _urut_kemiripan(milik_list, found)
    pilih_baru = hilang_id == "0" or not milik_list
    hilang_id = int(hilang_id) if hilang_id.isdigit() else None
    form = {"hilang": 0 if pilih_baru else hilang_id, "jawaban_ciri": jawaban_ciri, "keterangan": keterangan, "lokasi": lokasi, "nama": nama}
    errors: dict[str, str] = {}
    lost = None if pilih_baru else next((it for it in milik_list if it.id == hilang_id), None)
    foto_baru = None
    if not pilih_baru and lost is None:
        errors["hilang_id"] = "Pilih laporan barang hilangmu yang sesuai, atau pilih \u201cBelum dilaporkan\u201d."
    if pilih_baru:
        if not lokasi.strip():
            errors["lokasi"] = "Tulis kira-kira di mana barangmu hilang, misalnya Stasiun Malang."
        if foto_pemilik is None or not foto_pemilik.filename:
            errors["foto_pemilik"] = "Unggah satu foto barangmu (foto lama juga boleh) agar admin bisa membandingkannya."
        else:
            foto_baru, galat = await foto_util.simpan(foto_pemilik, potong=potong)
            if galat:
                errors["foto_pemilik"] = galat
    if len(jawaban_ciri.strip()) < 3:
        errors["jawaban_ciri"] = "Tulis satu ciri khusus yang hanya kamu tahu dari barangmu (minimal 3 huruf)."
    if errors:
        if foto_baru:
            (UPLOAD_DIR / foto_baru).unlink(missing_ok=True)
        return templates.TemplateResponse(request, "klaim.html", {
            "user": user, "found": found, "milik": milik, "form": form, "errors": errors, "aktif": "Cari"},
            status_code=400)

    if lost is None:  # buat laporan hilang otomatis
        lok = lokasi.strip()[:120]
        lost = Item(user_id=user.id, jenis="hilang", kategori=found.kategori, nama=nama.strip()[:60],
                    deskripsi=nama.strip()[:60] or f"Barang {found.kategori.lower()} di {lok}", ciri_khusus=jawaban_ciri.strip(),
                    lokasi=lok, path_foto=foto_baru, waktu_kejadian=datetime.now(),
                    vektor_fitur=matching.ke_bytes(matching.ekstrak(UPLOAD_DIR / foto_baru)), status="Hilang")
        db.add(lost)
        db.flush()
    m = db.scalars(select(Match).where(Match.lost_item_id == lost.id, Match.found_item_id == found.id)).first()
    if m is None:  # klaim dari pencarian: skor foto disimpan sebagai bahan admin, peringkat 0 = bukan dari top-5
        skor = matching.skor_foto_semua(lost.vektor_fitur, [(found.id, found.vektor_fitur)])
        m = Match(lost_item_id=lost.id, found_item_id=found.id, skor=skor.get(found.id, 0.0), peringkat=0)
        db.add(m)
        db.flush()
    errors = await _buat_klaim(db, user, m, lost, found, jawaban_ciri, keterangan, bukti_foto)
    if errors:
        db.rollback()
        if foto_baru:
            (UPLOAD_DIR / foto_baru).unlink(missing_ok=True)
        return templates.TemplateResponse(request, "klaim.html", {
            "user": user, "found": found, "milik": milik, "form": form, "errors": errors, "aktif": "Cari"},
            status_code=400)
    request.session["flash"] = "Klaim terkirim. Admin biasanya memeriksa dalam 1×24 jam; pantau statusnya di halaman ini."
    return RedirectResponse(f"/laporan/{lost.id}", status_code=303)
