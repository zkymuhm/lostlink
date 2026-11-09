# LOSTLINK — Intelligent Lost & Found Berbasis Image Matching

Kelompok 1 Manajemen Proyek, Teknik Informatika UIN Maulana Malik Ibrahim Malang.
Arsitektur tiga lapis (laporan M3): browser (Jinja2 + Bootstrap 5) → FastAPI → SQLite + folder `uploads/`.

## Status implementasi

| WBS | Modul | Status |
|---|---|---|
| 4.1 | Login dan registrasi berbasis peran | selesai |
| 4.2 | Pelaporan barang (foto, kategori, ciri, lokasi, waktu) | selesai |
| 4.3 | Pencarian dan filter (kata kunci, kategori, lokasi, tanggal, jenis) | selesai |
| 4.4 | Klaim, verifikasi ciri khusus, status 4 tahap, persetujuan admin | selesai |
| 4.5 | Frontend pengguna dan halaman admin | selesai (tahap penyempurnaan) |
| 5.1 | Dataset uji | selesai: 30 pasang + 27 pengecoh (`uji_kelayakan/data`) |
| 5.2 | Ekstraksi fitur ResNet18 (`app/matching.py`) | selesai |
| 5.3 | Rekomendasi top-5 + filter kategori/waktu | selesai |

Test otomatis: `python -m pytest -q` (15 test).

## Menjalankan (macOS, Python 3.11)

    cd ~/development/lostlink
    python3.11 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt

    # akun admin pertama
    python -m app.seed_admin "Arzaki Muhamad Fadil" admin@lostlink.local 081234567890 admin12345

    # (opsional) data demo dari dataset uji: akun alivia@lostlink.local / rahul@lostlink.local, sandi demo12345
    python -m app.seed_demo

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

## Endpoint

| Metode | Endpoint | Akses | KF |
|---|---|---|---|
| GET/POST | /register, /login · POST /logout | Publik | KF-01, KF-02 |
| GET | / | Pengguna | KF-12 |
| GET | /lapor · POST /laporan | Pengguna | KF-03 s.d. KF-06 |
| GET | /laporan (cari) · /laporan/{id} (detail & status) · /saya | Pengguna | KF-09, KF-11, KF-12 |
| GET | /rekomendasi/{item_id} | Pemilik laporan | KF-07, KF-08 |
| POST | /klaim | Pengguna | KF-10 |
| GET/POST | /admin/klaim · /admin/klaim/{id}/setujui · /tolak | Admin | KF-13 |
| GET/POST | /admin/laporan · /admin/laporan/{id}/hapus | Admin | KF-14 |
| GET/POST | /admin/pengguna · /admin/pengguna/{id}/nonaktif | Admin | KF-14 |

Pengguna biasa yang membuka /admin/* mendapat 403 (KNF-04). Foto disimpan di `uploads/` dengan nama acak.
