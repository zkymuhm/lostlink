"""Siapkan model pencocokan dan hitung ulang vektor semua laporan.

Jalankan dari folder proyek setelah mengganti model atau setelah clone baru:
    python -m app.perbarui_model

Model mengikuti LOSTLINK_MODEL (bawaan siglip2_base). Langkah:
  1. Membuat app/data/rerata_<model>.npy = rata-rata fitur foto acuan
     (uji_kelayakan/data bila ada; bila tidak, foto laporan di database).
  2. Membuat app/data/kalibrasi_<model>.json = batas persen tampilan, dihitung dari pasangan foto uji
     (hanya bila uji_kelayakan/data ada), sekaligus mencetak akurasi top-1/top-5 sebagai pemeriksaan.
  3. Menghitung ulang vektor fitur semua laporan di database dengan model sekarang.
  4. Memperbarui skor kecocokan yang sudah tersimpan (termasuk yang sedang diklaim).
"""
import json
import time

import numpy as np

from . import matching
from .config import ROOT, UPLOAD_DIR
from .database import SessionLocal
from .models import Item, Match

EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif")


def foto_acuan(db) -> list:
    data = ROOT / "uji_kelayakan" / "data"
    foto = sorted(p for sub in ("hilang", "temuan") if (data / sub).is_dir()
                  for p in (data / sub).iterdir() if p.suffix.lower() in EXT and not p.name.startswith("."))
    if len(foto) >= 20:
        print(f"Foto acuan: {len(foto)} foto dari uji_kelayakan/data")
        return foto
    foto = [UPLOAD_DIR / it.path_foto for it in db.query(Item).all() if (UPLOAD_DIR / it.path_foto).exists()]
    print(f"Foto acuan: {len(foto)} foto laporan di database")
    return foto


def kalibrasi(fitur: dict) -> dict | None:
    """Batas persen dari pasangan foto uji. fitur = {path: vektor sudah dinormalisasi}."""
    hilang = {p.name[:2]: v for p, v in fitur.items() if p.parent.name == "hilang" and p.name[:2].isdigit()}
    temuan = [(p.name[:2], v) for p, v in fitur.items() if p.parent.name == "temuan"]
    if len(hilang) < 10 or len(temuan) < 10:
        return None
    pos, neg, ranks = [], [], []
    T = np.stack([v for _, v in temuan])
    for kode, q in hilang.items():
        skor = T @ q
        benar = [j for j, (k, _) in enumerate(temuan) if k == kode]
        if not benar:
            continue
        pos.append(float(skor[benar[0]]))
        neg.extend(float(skor[j]) for j, (k, _) in enumerate(temuan) if k != kode)
        ranks.append(int((skor > skor[benar[0]]).sum()) + 1)
    dasar = float(np.percentile(neg, 95))
    rata_benar = float(np.mean(pos))
    penuh = dasar + (rata_benar - dasar) / 0.77  # rata-rata pasangan benar tampil sekitar 77%
    ranks = np.array(ranks)
    return {"model": matching.MODEL, "skor_dasar": round(dasar, 4), "skor_penuh": round(penuh, 4),
            "rata_pasangan_benar": round(rata_benar, 4), "p95_pasangan_salah": round(dasar, 4),
            "jumlah_pasangan": len(pos), "top1": round(float((ranks == 1).mean() * 100), 1),
            "top5": round(float((ranks <= 5).mean() * 100), 1)}


def main():
    if matching.fake_mode():
        raise SystemExit("Matikan LOSTLINK_FAKE_MODEL dulu.")
    t0 = time.perf_counter()
    with SessionLocal() as db:
        acuan = foto_acuan(db)
        if len(acuan) < 10:
            raise SystemExit("Butuh minimal 10 foto acuan. Isi uji_kelayakan/data atau jalankan python -m app.seed_demo dulu.")
        print(f"[1/4] Menghitung vektor rata-rata model {matching.MODEL} dari {len(acuan)} foto ...")
        mentah = {p: matching.fitur_mentah(matching.buka(p)) for p in acuan}
        rerata = np.mean(list(mentah.values()), axis=0).astype(np.float32)
        matching.RERATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        np.save(matching.RERATA_PATH, rerata)
        matching._rerata = rerata
        print(f"      tersimpan: {matching.RERATA_PATH.relative_to(ROOT)}")

        print("[2/4] Kalibrasi persen kemiripan ...")
        k = kalibrasi({p: matching._normal(v - rerata) for p, v in mentah.items()})
        if k:
            matching.KALIBRASI_PATH.write_text(json.dumps(k, indent=2))
            matching.SKOR_DASAR, matching.SKOR_PENUH = k["skor_dasar"], k["skor_penuh"]
            print(f"      {k['jumlah_pasangan']} pasangan: top-1 {k['top1']}%, top-5 {k['top5']}% | "
                  f"0% = skor {k['skor_dasar']}, 100% = skor {k['skor_penuh']}")
            print(f"      tersimpan: {matching.KALIBRASI_PATH.relative_to(ROOT)}")
        else:
            print("      dilewati: butuh pasangan foto di uji_kelayakan/data (memakai batas bawaan)")

        items = db.query(Item).all()
        print(f"[3/4] Menghitung ulang vektor {len(items)} laporan ...")
        hilang = 0
        for it in items:
            path = UPLOAD_DIR / it.path_foto
            if path.exists():
                it.vektor_fitur = matching.ke_bytes(matching.ekstrak(path))
            else:
                hilang += 1
        db.commit()
        if hilang:
            print(f"      {hilang} laporan dilewati karena fotonya tidak ada di folder uploads")

        matches = db.query(Match).all()
        print(f"[4/4] Memperbarui {len(matches)} skor kecocokan ...")
        for m in matches:
            a, b = db.get(Item, m.lost_item_id), db.get(Item, m.found_item_id)
            if a and b and a.vektor_fitur and b.vektor_fitur and len(a.vektor_fitur) == len(b.vektor_fitur):
                m.skor = float(matching.dari_bytes(a.vektor_fitur) @ matching.dari_bytes(b.vektor_fitur))
        db.commit()
    print(f"Selesai dalam {time.perf_counter() - t0:.0f} detik.")


if __name__ == "__main__":
    main()
