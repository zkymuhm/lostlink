"""Test case alur inti: lapor (4.2), cari (4.3), rekomendasi (5.3), klaim & admin (4.4, KF-13, KF-14)."""
import io
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import matching
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
    # hanya yang mirip ditampilkan; dua pengecoh (warna jauh berbeda) disembunyikan tapi bisa dibuka
    assert page.status_code == 200 and "4 barang temuan yang mirip" in page.text
    assert "4 barang temuan terdekat" in pemilik.get(f"/rekomendasi/{lost_id}?dekat=1").text
    # kandidat di bawah batas tampil disembunyikan, tetapi tetap bisa dibuka
    batas, matching.BATAS_TAMPIL = matching.BATAS_TAMPIL, 101
    try:
        sembunyi = pemilik.get(f"/rekomendasi/{lost_id}").text
        assert "Belum ada yang mirip sekarang" in sembunyi and "Tetap lihat" in sembunyi and "ll-rank" not in sembunyi
    finally:
        matching.BATAS_TAMPIL = batas

    with SessionLocal() as db:
        lost = db.get(Item, lost_id)
        assert lost.status == "Hilang" and lost.vektor_fitur and len(lost.vektor_fitur) == matching.DIM_PALSU * 4
        from app.models import Match
        top = db.query(Match).filter_by(lost_item_id=lost_id, peringkat=1).one()
        found = db.get(Item, top.found_item_id)
        assert found.deskripsi.startswith("Ransel hitam")  # foto merah peringkat 1
        match_id, found_id = top.id, found.id

    # tanpa filter -> dompet merah ikut muncul
    assert "kategori sama" in page.text  # data pendukung hanya menambah nilai, dompet beda kategori tetap tampil

    # ciri khusus tidak pernah tampil ke publik
    assert "stiker logo kampus" not in pemilik.get(f"/laporan/{found_id}").text
    assert "stiker logo kampus" not in pemilik.get("/laporan?q=ransel").text

    # klaim
    r = pemilik.post("/klaim", data={"match_id": match_id, "jawaban_ciri": "stiker logo kampus di kantong"})
    assert r.status_code == 303
    with SessionLocal() as db:
        assert db.get(Item, lost_id).status == "Diverifikasi" and db.get(Item, found_id).status == "Diverifikasi"
    halaman = pemilik.get(f"/laporan/{lost_id}").text
    assert "Terkunci" in halaman and "Klaimmu sedang diperiksa admin" in halaman
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
    assert "Barangmu sudah ditemukan" in detail and "Ini laporan barangmu yang hilang" not in detail


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


def test_foto_tetap_tersimpan_setelah_galat():
    """Bila form ditolak karena kolom lain, foto tidak perlu dipilih ulang."""
    import re as _re
    c = akun("Foto", "foto@test.id")
    r = c.post("/laporan", data={"jenis": "hilang", "kategori": "Tas", "lokasi": ""},
               files={"foto": ("a.jpg", foto((9, 9, 9)), "image/jpeg")})
    assert r.status_code == 400 and 'id="galat-lokasi"' in r.text and 'id="galat-foto"' not in r.text
    tmp = _re.search(r'name="foto_tmp" id="foto_tmp" value="(tmp_[0-9a-f]{32}\.jpg)"', r.text).group(1)
    assert "Foto sebelumnya masih tersimpan" in r.text
    r = c.post("/laporan", data={"jenis": "hilang", "kategori": "Tas", "lokasi": "Stasiun", "foto_tmp": tmp})
    assert r.status_code == 303
    # nama sembarang tidak boleh dipakai sebagai foto
    r = c.post("/laporan", data={"jenis": "hilang", "kategori": "Tas", "lokasi": "Stasiun", "foto_tmp": "../lostlink.db"})
    assert r.status_code == 400 and "Fotonya belum ada" in r.text


def test_persen_kemiripan_dikalibrasi():
    assert matching.persen(matching.SKOR_DASAR) == 0 and matching.persen(-0.1) == 0
    assert matching.persen(matching.SKOR_PENUH) == 100 and matching.persen(0.99) == 100
    assert matching.tingkat(0.95)[0] == "Sangat mirip" and matching.tingkat(0.1)[0] == "Kurang mirip" and matching.tingkat(0.35)[0] == "Cukup mirip"


def test_waktu_kosong_tidak_menyaring_temuan_lama():
    """Bug 10 Nov: waktu hilang dikosongkan -> barang yang ditemukan sebelum laporan dibuat tetap muncul."""
    penemu, pemilik = akun("Penemu lama", "penemu.lama@test.id"), akun("Pemilik lama", "pemilik.lama@test.id")
    lama = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%dT%H:%M")
    penemu.post("/laporan", data={"jenis": "temuan", "kategori": "Kunci", "lokasi": "Stasiun", "ciri_khusus": "ada stiker", "waktu": lama},
                files={"foto": ("a.jpg", foto((20, 120, 220)), "image/jpeg")})
    r = pemilik.post("/laporan", data={"jenis": "hilang", "kategori": "Kunci", "lokasi": "di jalan mawar"},
                     files={"foto": ("b.jpg", foto((20, 120, 220)), "image/jpeg")})
    lost_id = int(r.headers["location"].rsplit("/", 1)[1])
    r = pemilik.get(f"/rekomendasi/{lost_id}")
    assert "Waktu hilang belum diisi" in r.text and "Stasiun" in r.text
    with SessionLocal() as db:
        assert db.get(Item, lost_id).deskripsi == "Barang kunci di jalan mawar"


def test_data_pendukung_hanya_menambah():
    """Foto penentu utama; kategori/waktu/lokasi/nama hanya menambah skor, tidak pernah mengurangi."""
    from types import SimpleNamespace as N
    now = datetime.now()
    hilang = N(kategori="Lainnya", waktu_diketahui=True, waktu_kejadian=now - timedelta(days=2),
               lokasi="Stasiun Malang", nama="Case earbud biru", deskripsi="Case earbud biru")
    cocok = N(kategori="Lainnya", waktu_kejadian=now, lokasi="Stasiun Malang peron 2", nama="", deskripsi="Case earbud biru muda")
    beda = N(kategori="Tas", waktu_kejadian=now - timedelta(days=9), lokasi="Terminal Arjosari", nama="", deskripsi="Ransel hitam")
    s1, alasan = matching.skor_gabungan(hilang, cocok, 0.40)
    s2, alasan2 = matching.skor_gabungan(hilang, beda, 0.40)
    assert s1 > 0.40 and set(alasan) == {"kategori sama", "ditemukan setelah hilang"}  # teks & lokasi dimatikan (16 Nov)
    assert s2 == 0.40 and alasan2 == []  # data yang tidak cocok tidak mengurangi skor foto
    # selisih foto yang besar tidak bisa dibalik oleh data pendukung
    assert matching.skor_gabungan(hilang, cocok, 0.10)[0] < matching.skor_gabungan(hilang, beda, 0.40)[0]


def test_klaim_dari_pencarian_dengan_bukti():
    """Tombol "Ini barangku": tanpa laporan hilang cukup satu form; laporan hilang dibuat otomatis."""
    penemu, pemilik = akun("Penemu cari", "penemu.cari@test.id"), akun("Pemilik cari", "pemilik.cari@test.id")
    r = penemu.post("/laporan", data={"jenis": "temuan", "kategori": "Dompet", "lokasi": "Masjid Agung", "ciri_khusus": "ada foto kucing",
                                      "nama": "Dompet coklat"}, files={"foto": ("a.jpg", foto((120, 70, 30)), "image/jpeg")})
    found_id = int(r.headers["location"].rsplit("/", 1)[1])
    assert "Ini barangku" in pemilik.get(f"/laporan/{found_id}").text
    assert "Ini barangku" not in penemu.get(f"/laporan/{found_id}").text  # bukan untuk barang sendiri
    halaman = pemilik.get(f"/barang/{found_id}/klaim").text
    assert "Foto barangmu" in halaman and 'name="hilang_id" value="0"' in halaman
    # semua kolom wajib kosong -> galat per kolom, tidak ada laporan yang dibuat
    r = pemilik.post(f"/barang/{found_id}/klaim", data={"hilang_id": 0, "jawaban_ciri": ""})
    assert r.status_code == 400
    for kolom in ("foto_pemilik", "lokasi", "jawaban_ciri"):
        assert f'id="galat-{kolom}"' in r.text
    with SessionLocal() as db:
        assert db.query(Item).filter_by(jenis="hilang").join(Item.pelapor).filter_by(email="pemilik.cari@test.id").count() == 0
    r = pemilik.post(f"/barang/{found_id}/klaim",
                     data={"hilang_id": 0, "lokasi": "Masjid", "nama": "Dompet coklat saya", "jawaban_ciri": "foto kucing di dalam",
                           "keterangan": "hilang setelah salat jumat"},
                     files={"foto_pemilik": ("b.jpg", foto((120, 70, 30)), "image/jpeg"),
                            "bukti_foto": ("nota.jpg", foto((250, 250, 250)), "image/jpeg")})
    assert r.status_code == 303
    lost_id = int(r.headers["location"].rsplit("/", 1)[1])
    from app.models import Match, Verification
    with SessionLocal() as db:
        lost = db.get(Item, lost_id)
        assert lost.jenis == "hilang" and lost.kategori == "Dompet" and lost.nama == "Dompet coklat saya" and lost.vektor_fitur
        v = db.query(Verification).join(Match).filter(Match.found_item_id == found_id).one()
        assert v.bukti_foto.startswith("bukti_") and v.keterangan == "hilang setelah salat jumat"
        assert db.get(Match, v.match_id).peringkat == 0
        assert db.get(Item, found_id).status == "Diverifikasi" and lost.status == "Diverifikasi"
    assert pemilik.get(f"/barang/{found_id}/klaim").status_code == 409  # sudah diproses, tidak bisa diklaim lagi


def test_klaim_dari_pencarian_pakai_laporan_lama():
    penemu, pemilik = akun("Penemu 2", "penemu.dua@test.id"), akun("Pemilik 2", "pemilik.dua@test.id")
    r = penemu.post("/laporan", data={"jenis": "temuan", "kategori": "Kunci", "lokasi": "Terminal", "ciri_khusus": "gantungan bola"},
                    files={"foto": ("a.jpg", foto((20, 20, 200)), "image/jpeg")})
    found_id = int(r.headers["location"].rsplit("/", 1)[1])
    r = pemilik.post("/laporan", data={"jenis": "hilang", "kategori": "Kunci", "lokasi": "Terminal"},
                     files={"foto": ("b.jpg", foto((20, 20, 200)), "image/jpeg")})
    lost_id = int(r.headers["location"].rsplit("/", 1)[1])
    assert f'value="{lost_id}" checked' in pemilik.get(f"/barang/{found_id}/klaim").text  # laporan lama terpilih otomatis
    r = pemilik.post(f"/barang/{found_id}/klaim", data={"hilang_id": lost_id, "jawaban_ciri": "ada gantungan bola"})
    assert r.status_code == 303 and r.headers["location"] == f"/laporan/{lost_id}"


def test_potong_foto_di_form_lapor():
    """Alat potong: kotak "x,y,lebar,tinggi" (pecahan) dipakai server; nilai aneh diabaikan."""
    from app.config import UPLOAD_DIR
    from app.routers.laporan import _potong
    img = Image.new("RGB", (400, 300), (255, 255, 255))
    assert _potong(img, "0.25,0.5,0.5,0.5").size == (200, 150)
    for salah in ("", "abc", "0,0,1", "0,0,0.01,0.01", "-1,0,1,1", "0,0,2,1"):
        assert _potong(img, salah).size == (400, 300)
    c = akun("Potong", "potong@test.id")
    r = c.post("/laporan", data={"jenis": "hilang", "kategori": "Tas", "lokasi": "Stasiun", "potong": "0.15,0.1666,0.6,0.6333"},
               files={"foto": ("a.jpg", foto((200, 30, 30)), "image/jpeg")})
    item_id = int(r.headers["location"].rsplit("/", 1)[1])
    with SessionLocal() as db:
        simpan = Image.open(UPLOAD_DIR / db.get(Item, item_id).path_foto)
    assert simpan.size == (240, 190)
    r, g, b = simpan.getpixel((120, 95))
    assert r > 150 and g < 80  # yang tersisa hanya kotak merah (barangnya), latar abu terbuang


def test_klaim_dari_pencarian_wajib_pilih_laporan():
    """Laporan lama yang fotonya tidak mirip tidak dipilih otomatis; mengirim tanpa memilih ditolak."""
    def polos(warna):
        b = io.BytesIO()
        Image.new("RGB", (300, 300), warna).save(b, "JPEG")
        return b.getvalue()

    penemu, pemilik = akun("Penemu 3", "penemu.tiga@test.id"), akun("Pemilik 3", "pemilik.tiga@test.id")
    r = penemu.post("/laporan", data={"jenis": "temuan", "kategori": "Tas", "lokasi": "Kafe", "ciri_khusus": "resleting rusak"},
                    files={"foto": ("a.jpg", polos((230, 40, 40)), "image/jpeg")})
    found_id = int(r.headers["location"].rsplit("/", 1)[1])
    pemilik.post("/laporan", data={"jenis": "hilang", "kategori": "Kunci", "lokasi": "Terminal"},
                 files={"foto": ("b.jpg", polos((20, 200, 40)), "image/jpeg")})
    assert " checked" not in pemilik.get(f"/barang/{found_id}/klaim").text.split("2. Bukti kepemilikan")[0]
    r = pemilik.post(f"/barang/{found_id}/klaim", data={"jawaban_ciri": "resleting rusak"})
    assert r.status_code == 400 and 'id="galat-hilang_id"' in r.text


def test_rekomendasi_tanpa_laporan_dijelaskan_dan_tombol_kembali_ikut_asal():
    c = akun("Tanpa Laporan", "kosong@test.id")
    r = c.get("/rekomendasi")
    assert r.status_code == 200 and "Apa itu Rekomendasi?" in r.text
    temuan = akun("Penemu Kembali", "penemu.kembali@test.id")
    lapor(temuan, "temuan", (30, 160, 60))
    with SessionLocal() as db:
        iid = db.query(Item).filter_by(jenis="temuan").order_by(Item.id.desc()).first().id
    r = c.get(f"/laporan/{iid}", headers={"referer": "http://testserver/"})
    assert 'href="/"' in r.text and "Kembali ke beranda" in r.text
    r = c.get(f"/laporan/{iid}", headers={"referer": "http://testserver/laporan?q=tas&jenis=temuan"})
    assert "Kembali ke hasil pencarian" in r.text
    r = c.get(f"/laporan/{iid}", headers={"referer": "https://situs-lain.com/"})
    assert "Kembali ke pencarian" in r.text


def test_halaman_banding_dan_klaim_dari_situ():
    from app.models import Match

    pemilik = akun("Pembanding", "pembanding@test.id")
    penemu = akun("Penemu Banding", "penemu.banding@test.id")
    orang_lain = akun("Orang Lain", "orang.lain.banding@test.id")
    lapor(penemu, "temuan", (40, 90, 210), deskripsi="Botol biru tutup putih", ciri="ada goresan di bawah")
    r = lapor(pemilik, "hilang", (45, 95, 205), deskripsi="Botol minum biru")
    lost_id = int(r.headers["location"].rsplit("/", 1)[1])
    daftar = pemilik.get(f"/rekomendasi/{lost_id}").text
    assert f"/rekomendasi/{lost_id}/banding/" in daftar and "Bandingkan" in daftar
    with SessionLocal() as db:
        m = db.query(Match).filter_by(lost_item_id=lost_id).order_by(Match.peringkat).first()
        mid, found_id = m.id, m.found_item_id
    page = pemilik.get(f"/rekomendasi/{lost_id}/banding/{mid}")
    assert page.status_code == 200 and "Apakah ini barangmu?" in page.text and "Botol biru tutup putih" in page.text
    assert "ada goresan di bawah" not in page.text  # ciri khusus penemu tetap rahasia
    assert orang_lain.get(f"/rekomendasi/{lost_id}/banding/{mid}").status_code == 404
    # klaim tanpa ciri -> kembali ke halaman pembanding dengan pesan
    r = pemilik.post("/klaim", data={"match_id": mid, "jawaban_ciri": "", "asal": "banding"})
    assert r.status_code == 303 and f"/banding/{mid}" in r.headers["location"]
    assert "Tulis satu ciri khusus" in pemilik.get(r.headers["location"]).text
    r = pemilik.post("/klaim", data={"match_id": mid, "jawaban_ciri": "ada goresan di bawah", "asal": "banding"})
    assert r.status_code == 303 and r.headers["location"] == f"/laporan/{lost_id}"
    with SessionLocal() as db:
        assert db.get(Item, found_id).status == "Diverifikasi"


def test_kf05_format_dan_ukuran_foto():
    """KF-05: JPG di bawah 5 MB diterima; PNG lebih dari 5 MB dan PDF ditolak dengan pesan."""
    import os
    c = akun("Ukuran", "ukuran@test.id")
    data = {"jenis": "hilang", "kategori": "Tas", "lokasi": "Stasiun"}
    r = c.post("/laporan", data=data, files={"foto": ("kecil.jpg", foto((30, 30, 30)), "image/jpeg")})
    assert r.status_code == 303
    besar = io.BytesIO()
    Image.frombytes("RGB", (1500, 1500), os.urandom(1500 * 1500 * 3)).save(besar, "PNG")  # derau acak: PNG > 5 MB
    assert besar.tell() > 5 * 1024 * 1024
    r = c.post("/laporan", data=data, files={"foto": ("besar.png", besar.getvalue(), "image/png")})
    assert r.status_code == 400 and "lebih dari batas 5 MB" in r.text
    r = c.post("/laporan", data=data, files={"foto": ("dokumen.pdf", b"%PDF-1.4 bukan foto", "application/pdf")})
    assert r.status_code == 400 and "bukan format foto yang didukung" in r.text
