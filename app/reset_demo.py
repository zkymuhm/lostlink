"""Kembalikan database ke kondisi awal untuk pengujian: 3 akun + data demo.

Pemakaian (MATIKAN server dulu, venv aktif, dari folder proyek):
    python -m app.reset_demo                 # kata sandi admin: admin12345
    python -m app.reset_demo KataSandiBaru   # kata sandi admin pilihan sendiri

Langkah:
  1. lostlink.db dan folder uploads/ dipindah ke cadangan/<tanggal-jam>/ (tidak dihapus).
  2. Database baru dibuat, berisi akun admin@lostlink.local.
  3. Data demo diisi ulang (python -m app.seed_demo): alivia@ dan rahul@lostlink.local (kata sandi demo12345),
     6 laporan hilang, 57 barang temuan, 1 klaim menunggu, 1 barang sudah dikembalikan.
"""
import shutil
import sys
from datetime import datetime

from .config import ROOT, UPLOAD_DIR
from .database import DATABASE_URL


def main(argv):
    sandi = argv[0] if argv else "admin12345"
    if len(sandi) < 8:
        print("Kata sandi admin minimal 8 karakter.")
        return 1
    if not DATABASE_URL.startswith("sqlite:///"):
        print("Hanya untuk database SQLite lokal.")
        return 1
    db_path = (ROOT / DATABASE_URL.removeprefix("sqlite:///")).resolve() if not DATABASE_URL.startswith("sqlite:////") \
        else __import__("pathlib").Path(DATABASE_URL.removeprefix("sqlite:///"))
    cadangan = ROOT / "cadangan" / datetime.now().strftime("%Y%m%d-%H%M%S")
    cadangan.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        shutil.move(str(db_path), cadangan / db_path.name)
    if UPLOAD_DIR.exists():
        shutil.move(str(UPLOAD_DIR), cadangan / "uploads")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[1/3] Data lama dicadangkan ke {cadangan.relative_to(ROOT)}")

    # impor setelah file lama dipindah agar koneksi database menunjuk ke file baru
    from . import seed_admin, seed_demo
    from .database import Base, engine, pastikan_kolom

    Base.metadata.create_all(bind=engine)
    pastikan_kolom()
    seed_admin.main(["Admin LOSTLINK", "admin@lostlink.local", "081200000000", sandi])
    print("[2/3] Akun admin dibuat: admin@lostlink.local")
    print("[3/3] Mengisi data demo ...")
    hasil = seed_demo.main()
    print("\nSelesai. Akun untuk pengujian:")
    print(f"  admin@lostlink.local  / {'(kata sandi pilihanmu)' if argv else 'admin12345'}")
    print("  alivia@lostlink.local / demo12345")
    print("  rahul@lostlink.local  / demo12345")
    print(f"Data lama tetap ada di {cadangan.relative_to(ROOT)} bila dibutuhkan.")
    return hasil or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
