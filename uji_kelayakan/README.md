# Uji kelayakan image matching (WBS 2.4 / 5.1)

- `lostlink_uji.py` — script uji: ResNet18 pre-trained + cosine similarity + top-5.
- `data/hilang/` — 25 foto pertama tiap barang (`01_kuas.jpg` … `25_gelas.jpg`).
- `data/temuan/` — 25 foto kedua dengan nama yang sama + 27 pengecoh (`x01.jpg` … `x27.jpg`).
- `data/daftar_nama.csv` — nama baru ↔ nama file asli dari WhatsApp/kamera.
- `hasil/` — hasil uji ulang 9 Nov 2026 di laptop HP ZBook 15 G2 (CPU):
  top-1 21/25 (84%), top-5 24/25 (96%), rata-rata 0,355 detik per foto.

Folder `data/` tidak diunggah ke GitHub (lihat `.gitignore`) karena ukurannya ±150 MB;
salinannya ada di Google Drive `LOSTLINK_uji/data`.

Menjalankan ulang (dari folder ini, venv proyek aktif):

    python lostlink_uji.py

Menambah pasangan baru: beri nama `26_namabarang.jpg` di `hilang/` dan `temuan/`,
pengecoh diberi awalan `x`.
