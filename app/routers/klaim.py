"""WBS 5.3 (rekomendasi top-5) dan 4.4 (klaim + verifikasi ciri khusus)."""
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import matching
from ..auth import current_user
from ..database import get_db
from ..models import Item, Match, User, Verification
from ..templating import templates

router = APIRouter()
TOP_K = 5


@router.get("/rekomendasi")
def rekomendasi_terbaru(user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.scalars(select(Item).where(Item.user_id == user.id, Item.jenis == "hilang").order_by(Item.dibuat_pada.desc())).first()
    return RedirectResponse(f"/rekomendasi/{item.id}" if item else "/lapor?jenis=hilang", status_code=303)


@router.get("/rekomendasi/{item_id}")
def rekomendasi(item_id: int, request: Request, semua: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(404, "Laporan tidak ditemukan atau bukan milik Anda.")
    if item.jenis != "hilang":
        return RedirectResponse(f"/laporan/{item.id}", status_code=303)

    t0 = time.perf_counter()
    stmt = select(Item.id, Item.vektor_fitur).where(Item.jenis == "temuan", Item.status == "Ditemukan")
    if not semua:  # filter kategori dan waktu (mitigasi risiko R1 di proposal)
        stmt = stmt.where(Item.kategori == item.kategori, Item.waktu_kejadian >= item.waktu_kejadian - timedelta(days=1))
    hasil = matching.top_k(item.vektor_fitur, db.execute(stmt).all(), TOP_K)
    durasi = time.perf_counter() - t0

    # Simpan ke tabel matches. Pasangan (hilang, temuan) yang sama memakai baris yang sama agar match_id stabil;
    # baris yang tidak lagi masuk top-5 dihapus kecuali sudah pernah diklaim.
    lama = {m.found_item_id: m for m in db.scalars(select(Match).where(Match.lost_item_id == item.id))}
    diklaim = set(db.scalars(select(Verification.match_id)))
    baru_ids = {fid for fid, _ in hasil}
    for fid, m in lama.items():
        if fid not in baru_ids and m.id not in diklaim:
            db.delete(m)
    kandidat = []
    for rank, (fid, skor) in enumerate(hasil, start=1):
        m = lama.get(fid)
        if m is None:
            m = Match(lost_item_id=item.id, found_item_id=fid, skor=skor, peringkat=rank)
            db.add(m)
            db.flush()
        else:
            m.skor, m.peringkat = skor, rank
        kandidat.append({"match": m, "item": db.get(Item, fid), "skor": skor, "rank": rank})
    db.commit()

    pending = db.scalars(select(Verification).join(Match).where(Match.lost_item_id == item.id, Verification.keputusan_admin.is_(None))).first()
    pilih = request.query_params.get("klaim")
    pilih_k = next((k for k in kandidat if str(k["match"].id) == pilih), None)
    return templates.TemplateResponse(request, "rekomendasi.html", {
        "user": user, "item": item, "kandidat": kandidat, "semua": semua, "durasi": durasi, "pending": pending,
        "pilih": pilih_k, "error": request.session.pop("klaim_error", None), "flash": request.session.pop("flash", None),
        "aktif": "Rekomendasi"})


@router.post("/klaim")
def ajukan_klaim(request: Request, match_id: int = Form(...), jawaban_ciri: str = Form(""),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(Match, match_id)
    lost = db.get(Item, m.lost_item_id) if m else None
    if m is None or lost is None or lost.user_id != user.id:
        raise HTTPException(404, "Kecocokan tidak ditemukan.")
    found = db.get(Item, m.found_item_id)
    if lost.status != "Hilang" or found is None or found.status != "Ditemukan":
        raise HTTPException(409, "Barang ini sudah dalam proses verifikasi atau sudah dikembalikan.")
    if len(jawaban_ciri.strip()) < 3:
        request.session["klaim_error"] = "Tulis jawaban ciri khusus (minimal 3 karakter)."
        return RedirectResponse(f"/rekomendasi/{lost.id}?klaim={m.id}", status_code=303)

    db.add(Verification(match_id=m.id, claimant_id=user.id, jawaban_ciri=jawaban_ciri.strip()))
    lost.status = "Diverifikasi"
    found.status = "Diverifikasi"
    db.commit()
    request.session["flash"] = "Klaim terkirim. Admin akan mencocokkan jawaban Anda dengan ciri khusus dari penemu."
    return RedirectResponse(f"/laporan/{lost.id}", status_code=303)
