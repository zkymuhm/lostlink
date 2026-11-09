"""Mengisi data demo dari dataset uji (uji_kelayakan/data) untuk presentasi.

Pemakaian (venv aktif, dari folder proyek):
    python -m app.seed_demo

Membuat 2 akun demo (kata sandi demo12345):
  - alivia@lostlink.local  -> pemilik, 6 laporan barang hilang
  - rahul@lostlink.local   -> penemu, 25 barang temuan + 27 pengecoh
Lalu 1 klaim menunggu admin (dompet kulit) dan 1 barang sudah dikembalikan (helm).
"""
import sys
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from . import matching
from .auth import hash_password
from .config import ROOT, UPLOAD_DIR
from .database import Base, SessionLocal, engine
from .models import Item, Match, User, Verification

DATA = ROOT / "uji_kelayakan" / "data"
LOKASI = ["Perpustakaan pusat", "Gedung A", "Gedung B", "Kantin", "Masjid Ulul Albab", "Lab komputer", "Parkiran motor"]

# id: (deskripsi, kategori, ciri khusus)
BARANG = {
    "01": ("Kuas cat kayu gagang merah", "Lainnya", "ada tulisan 2 inch di besi"),
    "02": ("Tang potong gagang biru", "Lainnya", "merek PGPC di gagang"),
    "03": ("Buku Madilog Tan Malaka", "Lainnya", "ada nama Rahul di halaman pertama"),
    "04": ("HP Redmi hitam", "Ponsel", "casing belakang ada goresan kecil"),
    "05": ("Pulpen gel hitam", "Lainnya", "tutup pulpen hilang"),
    "06": ("Sepatu kanvas putih", "Lainnya", "tali kiri lebih panjang"),
    "07": ("Cat akrilik V-TEC 12 warna", "Lainnya", "warna putih sudah habis"),
    "08": ("Sepatu Adidas biru muda", "Lainnya", "ada inisial A di lidah sepatu"),
    "09": ("Gantungan kunci mobil biru", "Kunci", "ring gantungan sedikit bengkok"),
    "10": ("Dompet kulit hitam lipat", "Dompet", "ada KTM UIN atas nama Alivia"),
    "11": ("Lanyard HIMATIF dengan ID card", "Lainnya", "ID card nomor 240605110073"),
    "12": ("Parfum botol hitam", "Lainnya", "isi tinggal setengah"),
    "13": ("Rubik 3x3", "Lainnya", "stiker kuning sudah pudar"),
    "14": ("Deodoran roll-on Rexona", "Lainnya", "tutup ada retak"),
    "15": ("Sabun Lifebuoy batang", "Lainnya", "kemasan belum dibuka"),
    "16": ("Dompet anyaman hitam kecil", "Dompet", "ada kartu e-money di dalam"),
    "17": ("Botol minyak aromaterapi hijau", "Lainnya", "label sedikit sobek"),
    "18": ("Pouch kanvas krem", "Tas", "ada tulisan My Beauty My Rules"),
    "19": ("Helm putih kaca hitam", "Lainnya", "ada stiker Cargloss di kiri"),
    "20": ("Parfum Aphrodite merah", "Lainnya", "tutup emas lecet"),
    "21": ("Boneka gantungan tas", "Lainnya", "ada label merah di kaki"),
    "22": ("Laptop MacBook abu-abu", "Lainnya", "ada stiker di bagian bawah"),
    "23": ("Keyboard mekanik 60%", "Lainnya", "tombol spasi agak macet"),
    "24": ("Case earbud biru muda", "Lainnya", "ada tali gantungan krem"),
    "25": ("Gelas kertas bergambar anime", "Lainnya", "ada nama Rafa di bawah gelas"),
}
PENGECOH = ["Post-it kuning", "Gelas plastik biru", "Lem tube", "Mouse wireless hitam", "Charger putih", "Dompet Levi's cokelat",
            "Case earbud hitam", "Charger iPad putih", "Buku catatan spiral", "Gunting gagang hitam", "Parfum Legend", "Spray Adidas",
            "Gantungan kunci karabiner", "Parfum Obsession merah", "Stik PS hitam", "Case earphone Lucky Bear", "Kacamata hitam",
            "Sisir hitam", "Parfum pink bunga", "Sunscreen Azarine", "Spray oranye", "Spray Fresh biru", "Mouse hitam",
            "Kaleng oranye", "Spray putih", "Spray biru", "Keyboard putih merah"]
KATEGORI_PENGECOH = {6: "Dompet", 13: "Kunci"}
HILANG_ALIVIA = ["08", "10", "13", "19", "22", "11"]


def simpan_foto(src) -> tuple[str, bytes]:
    img = matching.buka(src)
    img.thumbnail((1600, 1600))
    nama = f"{uuid.uuid4().hex}.jpg"
    img.save(UPLOAD_DIR / nama, "JPEG", quality=88)
    return nama, matching.ke_bytes(matching.ekstrak(UPLOAD_DIR / nama))


def akun(db, nama, email, kontak):
    u = User(nama=nama, email=email, no_kontak=kontak, password_hash=hash_password("demo12345"), peran="pengguna")
    db.add(u)
    db.flush()
    return u


def main():
    if not (DATA / "hilang").is_dir():
        print(f"Dataset tidak ditemukan di {DATA}")
        return 1
    Base.metadata.create_all(bind=engine)
    t0 = time.perf_counter()
    matching.siapkan_model()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == "alivia@lostlink.local")):
            print("Data demo sudah ada. Hapus file lostlink.db dan folder uploads/ bila ingin mengisi ulang.")
            return 0
        alivia = akun(db, "Alivia Wahyu Riandini", "alivia@lostlink.local", "081234500073")
        rahul = akun(db, "Rahul Surya Wibowo", "rahul@lostlink.local", "081234500164")
        now = datetime.now().replace(second=0, microsecond=0)

        temuan = {}
        for i, (bid, (desk, kat, ciri)) in enumerate(BARANG.items()):
            nama, vek = simpan_foto(next((DATA / "temuan").glob(bid + "_*")))
            it = Item(user_id=rahul.id, jenis="temuan", kategori=kat, deskripsi=desk, ciri_khusus=ciri, lokasi=LOKASI[i % len(LOKASI)],
                      waktu_kejadian=now - timedelta(days=1 + i % 6, hours=i % 5), path_foto=nama, vektor_fitur=vek, status="Ditemukan")
            db.add(it)
            temuan[bid] = it
            print(f"  temuan {bid} {desk}")
        for j, desk in enumerate(PENGECOH, start=1):
            nama, vek = simpan_foto(DATA / "temuan" / f"x{j:02d}.jpg")
            db.add(Item(user_id=rahul.id, jenis="temuan", kategori=KATEGORI_PENGECOH.get(j, "Lainnya"), deskripsi=desk,
                        ciri_khusus="-", lokasi=LOKASI[j % len(LOKASI)], waktu_kejadian=now - timedelta(days=j % 7, hours=j % 9),
                        path_foto=nama, vektor_fitur=vek, status="Ditemukan"))
        print(f"  {len(PENGECOH)} pengecoh")

        hilang = {}
        for bid in HILANG_ALIVIA:
            desk, kat, ciri = BARANG[bid]
            src = next((DATA / "hilang").glob(bid + "_*"))
            nama, vek = simpan_foto(src)
            ref = temuan[bid]
            it = Item(user_id=alivia.id, jenis="hilang", kategori=kat, deskripsi=desk, ciri_khusus=ciri, lokasi=ref.lokasi,
                      waktu_kejadian=ref.waktu_kejadian - timedelta(days=1), path_foto=nama, vektor_fitur=vek, status="Hilang")
            db.add(it)
            hilang[bid] = it
            print(f"  hilang {bid} {desk}")
        db.flush()

        def klaim(bid, jawaban, keputusan=None):
            lost, found = hilang[bid], temuan[bid]
            skor = float(matching.dari_bytes(lost.vektor_fitur) @ matching.dari_bytes(found.vektor_fitur))
            m = Match(lost_item_id=lost.id, found_item_id=found.id, skor=skor, peringkat=1)
            db.add(m)
            db.flush()
            v = Verification(match_id=m.id, claimant_id=alivia.id, jawaban_ciri=jawaban)
            if keputusan:
                admin = db.scalar(select(User).where(User.peran == "admin"))
                v.keputusan_admin, v.hasil = keputusan, "cocok"
                v.admin_id, v.diputuskan_pada = admin.id if admin else None, now
                lost.status = found.status = "Dikembalikan"
            else:
                lost.status = found.status = "Diverifikasi"
            db.add(v)

        klaim("10", "di dalamnya ada KTM UIN Malang atas nama saya, Alivia")
        klaim("19", "ada stiker Cargloss di sisi kiri helm", keputusan="disetujui")
        db.commit()
    print(f"Selesai dalam {time.perf_counter() - t0:.1f} detik. Login demo: alivia@lostlink.local / demo12345")
    return 0


if __name__ == "__main__":
    sys.exit(main())
