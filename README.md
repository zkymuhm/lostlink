# LOSTLINK — Intelligent Lost & Found Berbasis Image Matching

Kelompok 1 Manajemen Proyek, Teknik Informatika UIN Maulana Malik Ibrahim Malang.
Arsitektur tiga lapis (laporan M3): browser (Jinja2 + Bootstrap 5) → FastAPI → SQLite + folder `uploads/`.

## Status implementasi

| WBS | Modul | Status |
|---|---|---|
| 4.1 | Login dan registrasi berbasis peran | selesai (10 test lulus) |
| 4.2 | Pelaporan barang | belum |
| 4.3 | Pencarian dan filter | belum |
| 4.4 | Verifikasi dan status | belum |
| 4.5 | Frontend dan halaman admin | template dasar, login, registrasi |
| 5.1 | Dataset uji | 25/30 pasang (`uji_kelayakan/data`) |
| 5.2 | Ekstraksi fitur | prototipe di `uji_kelayakan/lostlink_uji.py` |
| 5.3 | API rekomendasi | belum |

## Menjalankan (macOS, Python 3.11)

    cd ~/development/lostlink
    python3.11 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt

    # akun admin pertama
    python -m app.seed_admin "Arzaki Muhamad Fadil" admin@lostlink.local 081234567890 admin12345

    # jalankan server, lalu buka http://127.0.0.1:8000
    uvicorn app.main:app --reload

    # test
    python -m pytest -q

## Struktur folder

    lostlink/
    ├── app/
    │   ├── main.py          # aplikasi FastAPI, rute beranda dan admin
    │   ├── database.py      # koneksi SQLite
    │   ├── models.py        # tabel users, items, matches, verifications
    │   ├── auth.py          # hash bcrypt, sesi, cek peran
    │   ├── seed_admin.py    # membuat akun admin
    │   ├── routers/auth.py  # /register, /login, /logout (WBS 4.1)
    │   ├── templates/       # halaman Jinja2
    │   └── static/css/      # Bootstrap 5.3.3 (lokal) + style.css
    ├── uploads/             # foto laporan (tidak diunggah ke GitHub)
    ├── tests/               # pytest
    ├── uji_kelayakan/       # script, dataset, dan hasil uji image matching
    └── requirements.txt

## Endpoint yang sudah ada

| Metode | Endpoint | Akses | KF |
|---|---|---|---|
| GET/POST | /register | Publik | KF-01 |
| GET/POST | /login | Publik | KF-02 |
| POST | /logout | Pengguna, admin | KF-02 |
| GET | / | Pengguna (admin dialihkan ke /admin/klaim) | KF-12 |
| GET | /admin/klaim | Admin (pengguna mendapat 403, KNF-04) | KF-13 |
