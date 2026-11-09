"""Test case alur inti: lapor (4.2), cari (4.3), rekomendasi (5.3), klaim & admin (4.4, KF-13, KF-14)."""
import io
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.database import SessionLocal
from app.main import app
from app.models import Item, User
from app.seed_admin import main as seed_admin

WAKTU = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
WAKTU_TEMUAN = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")


def foto(warna, bentuk=(0, 0), ukuran=(400, 300)) -> bytes:
    img = Image.new("RGB", ukuran, (235, 235, 235))
    d = ImageDraw.Draw(img)
    d.rectangle([60 + bentuk[0], 50 + bentuk[1], 300 + bentuk[0], 240 + bentuk[1]], fill=warna)
    b = io.BytesIO()
    img.save(b, "JPEG")
    return b.getvalue()


def akun(nama, email):
    c = TestClient(app, follow_redirects=False)
    c.post("/register", data={"nama": nama, "email": email, "no_kontak": "081234567890",
                              "password": "rahasia123", "password2": "rahasia123", "setuju": "1"})
    assert c.post("/login", data={"email": email, "password": "rahasia123"}).status_code == 303
    return c


def lapor(c, jenis, warna, ciri="stiker kampus di dalam", kategori="Tas", lokasi="Perpustakaan", deskripsi="Ransel hitam dua kantong",
          waktu=None, bentuk=(0, 0)):
    data = {"jenis": jenis, "kategori": kategori, "deskripsi": deskripsi, "ciri_khusus": ciri, "lokasi": lokasi,
            "waktu": waktu or (WAKTU if jenis == "hilang" else WAKTU_TEMUAN)}
    return c.post("/laporan", data=data, files={"foto": ("barang.jpg", foto(warna, bentuk), "image/jpeg")})


def test_alur_lengkap():
    pemilik = akun("Alivia", "alivia2@test.id")
    penemu = akun("Rahul", "rahul@test.id")
    seed_admin(["Admin", "admin2@test.id", "081111111111", "admin12345"])
    admin = TestClient(app, follow_redirects=False)
    admin.post("/login", data={"email": "admin2@test.id", "password": "admin12345"})

    # penemu melapor 3 barang temuan: satu mirip (merah), dua pengecoh
    r = lapor(penemu, "temuan", (200, 30, 30), ciri="ada stiker logo kampus", bentuk=(10, 5))
    assert r.status_code == 303 and r.headers["location"].startswith("/laporan/")
    lapor(penemu, "temuan", (30, 30, 200), deskripsi="Tas biru")
    lapor(penemu, "temuan", (30, 160, 30), deskripsi="Tas hijau")
    lapor(penemu, "temuan", (200, 30, 30), kategori="Dompet", deskripsi="Dompet merah")  # beda kategori -> terfilter

    # pemilik melapor barang hilang -> langsung diarahkan ke rekomendasi
    r = lapor(pemilik, "hilang", (205, 35, 35))
    assert r.headers["location"].startswith("/rekomendasi/")
    lost_id = int(r.headers["location"].rsplit("/", 1)[1])
    page = pemilik.get(f"/rekomendasi/{lost_id}")
    assert page.status_code == 200 and "3 barang temuan paling mirip" in page.text

    with SessionLocal() as db:
        lost = db.get(Item, lost_id)
        assert lost.status == "Hilang" and lost.vektor_fitur and len(lost.vektor_fitur) == 512 * 4
        from app.models import Match
        top = db.query(Match).filter_by(lost_item_id=lost_id, peringkat=1).one()
        found = db.get(Item, top.found_item_id)
        assert found.deskripsi.startswith("Ransel hitam")  # foto merah peringkat 1
        match_id, found_id = top.id, found.id

    # tanpa filter -> dompet merah ikut muncul
    assert "4 barang temuan paling mirip" in pemilik.get(f"/rekomendasi/{lost_id}?semua=1").text

    # ciri khusus tidak pernah tampil ke publik
    assert "stiker logo kampus" not in pemilik.get(f"/laporan/{found_id}").text
    assert "stiker logo kampus" not in pemilik.get("/laporan?q=ransel").text

    # klaim
    r = pemilik.post("/klaim", data={"match_id": match_id, "jawaban_ciri": "stiker logo kampus di kantong"})
    assert r.status_code == 303
    with SessionLocal() as db:
        assert db.get(Item, lost_id).status == "Diverifikasi" and db.get(Item, found_id).status == "Diverifikasi"
    assert "Terkunci" in pemilik.get(f"/laporan/{lost_id}").text
    assert pemilik.post("/klaim", data={"match_id": match_id, "jawaban_ciri": "lagi"}).status_code == 409

    # admin melihat klaim lalu menyetujui -> Dikembalikan, kontak terbuka
    page = admin.get("/admin/klaim")
    assert "ada stiker logo kampus" in page.text and "stiker logo kampus di kantong" in page.text
    from app.models import Verification
    with SessionLocal() as db:
        vid = db.query(Verification).filter_by(match_id=match_id).one().id
    assert pemilik.post(f"/admin/klaim/{vid}/setujui").status_code == 403  # KNF-04
    assert admin.post(f"/admin/klaim/{vid}/setujui").status_code == 303
    with SessionLocal() as db:
        assert db.get(Item, lost_id).status == "Dikembalikan" and db.get(Item, found_id).status == "Dikembalikan"
    detail = pemilik.get(f"/laporan/{lost_id}").text
    assert "081234567890" in detail and "Rahul" in detail


def test_klaim_ditolak_status_kembali():
    pemilik = akun("Pemilik B", "b@test.id")
    penemu = akun("Penemu B", "pb@test.id")
    admin = TestClient(app, follow_redirects=False)
    admin.post("/login", data={"email": "admin2@test.id", "password": "admin12345"})
    lapor(penemu, "temuan", (90, 60, 20), kategori="Kunci", deskripsi="Kunci motor cokelat")
    lost_id = int(lapor(pemilik, "hilang", (95, 62, 22), kategori="Kunci", deskripsi="Kunci motor").headers["location"].rsplit("/", 1)[1])
    pemilik.get(f"/rekomendasi/{lost_id}")
    from app.models import Match, Verification
    with SessionLocal() as db:
        m = db.query(Match).filter_by(lost_item_id=lost_id, peringkat=1).one()
        mid, fid = m.id, m.found_item_id
    pemilik.post("/klaim", data={"match_id": mid, "jawaban_ciri": "gantungan boneka"})
    with SessionLocal() as db:
        vid = db.query(Verification).filter_by(match_id=mid).one().id
    admin.post(f"/admin/klaim/{vid}/tolak")
    with SessionLocal() as db:
        assert db.get(Item, lost_id).status == "Hilang" and db.get(Item, fid).status == "Ditemukan"


def test_validasi_lapor():
    c = akun("Validasi", "val@test.id")
    r = c.post("/laporan", data={"jenis": "hilang", "kategori": "", "deskripsi": "", "ciri_khusus": "", "lokasi": "", "waktu": ""})
    assert r.status_code == 400
    for msg in ["Fotonya belum ada", "Pilih kategori", "perkiraan lokasinya", "3 hal"]:
        assert msg in r.text
    # barang temuan wajib punya ciri khusus
    r = c.post("/laporan", data={"jenis": "temuan", "kategori": "Tas", "lokasi": "Kantin", "ciri_khusus": ""},
               files={"foto": ("a.jpg", foto((1, 1, 1)), "image/jpeg")})
    assert r.status_code == 400 and "ciri khusus yang hanya diketahui" in r.text
    # barang hilang cukup foto + kategori + lokasi; detail dilengkapi nanti
    r = c.post("/laporan", data={"jenis": "hilang", "kategori": "Tas", "lokasi": "Kantin"},
               files={"foto": ("a.jpg", foto((5, 5, 5)), "image/jpeg")})
    assert r.status_code == 303
    item_id = int(r.headers["location"].rsplit("/", 1)[1])
    with SessionLocal() as db:
        it = db.get(Item, item_id)
        assert it.deskripsi == "Barang tas di Kantin" and it.ciri_khusus == ""
    r = c.post(f"/laporan/{item_id}/ubah", data={"kategori": "Tas", "lokasi": "Kantin lantai 2", "deskripsi": "Tas hitam",
                                                 "ciri_khusus": "ada nama saya", "waktu": WAKTU})
    assert r.status_code == 303
    with SessionLocal() as db:
        it = db.get(Item, item_id)
        assert it.deskripsi == "Tas hitam" and it.ciri_khusus == "ada nama saya" and it.lokasi == "Kantin lantai 2"
    lain = akun("Orang lain", "lain@test.id")
    assert lain.get(f"/laporan/{item_id}/ubah").status_code == 404
    bukan_foto = c.post("/laporan", data={"jenis": "hilang", "kategori": "Tas", "deskripsi": "Tas hitam", "ciri_khusus": "abc",
                                          "lokasi": "Kantin", "waktu": WAKTU}, files={"foto": ("a.jpg", b"bukan gambar", "image/jpeg")})
    assert bukan_foto.status_code == 400 and "bukan foto" in bukan_foto.text


def test_pencarian_filter():
    c = akun("Pencari", "cari@test.id")
    lapor(c, "temuan", (10, 10, 10), kategori="Ponsel", lokasi="Gedung B", deskripsi="HP Redmi hitam")
    assert "HP Redmi hitam" in c.get("/laporan?q=redmi").text
    assert "HP Redmi hitam" not in c.get("/laporan?q=redmi&kategori=Tas").text
    assert "HP Redmi hitam" in c.get("/laporan?lokasi=gedung b&jenis=temuan").text
    assert "HP Redmi hitam" not in c.get("/laporan?q=redmi&jenis=hilang").text
    besok = (datetime.now() + timedelta(days=1)).date().isoformat()
    assert "HP Redmi hitam" not in c.get(f"/laporan?q=redmi&dari={besok}").text
    assert c.get("/").status_code == 200 and c.get("/saya").status_code == 200


def test_admin_hapus_laporan_dan_nonaktif():
    c = akun("Nakal", "nakal@test.id")
    loc = lapor(c, "temuan", (1, 2, 3), deskripsi="Laporan palsu sekali").headers["location"]
    item_id = int(loc.rsplit("/", 1)[1])
    admin = TestClient(app, follow_redirects=False)
    admin.post("/login", data={"email": "admin2@test.id", "password": "admin12345"})
    assert "Laporan palsu" in admin.get("/admin/laporan").text
    admin.post(f"/admin/laporan/{item_id}/hapus")
    with SessionLocal() as db:
        assert db.get(Item, item_id) is None
        uid = db.query(User).filter_by(email="nakal@test.id").one().id
    assert admin.get("/admin/pengguna").status_code == 200
    admin.post(f"/admin/pengguna/{uid}/nonaktif")
    assert c.get("/saya").status_code == 303  # sesi lama ikut tidak berlaku
    assert c.post("/login", data={"email": "nakal@test.id", "password": "rahasia123"}).status_code == 401
