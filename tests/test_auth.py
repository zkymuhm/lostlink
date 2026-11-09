"""Test case WBS 4.1: registrasi, login, hak akses peran (KF-01, KF-02, KNF-04, KF-14)."""
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import User
from app.seed_admin import main as seed_admin

DATA = {"nama": "Alivia", "email": "alivia@test.id", "no_kontak": "081234567890",
        "password": "rahasia123", "password2": "rahasia123", "setuju": "1"}


def client():
    return TestClient(app, follow_redirects=False)


def login(c, email, pw):
    return c.post("/login", data={"email": email, "password": pw})


def test_halaman_publik_tampil():
    c = client()
    assert c.get("/login").status_code == 200
    assert c.get("/register").status_code == 200


def test_pengunjung_melihat_landing_dan_halaman_privat_ke_login():
    c = client()
    r = c.get("/")
    assert r.status_code == 200 and "Cara kerjanya" in r.text
    r = c.get("/saya")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_registrasi_berhasil_dan_password_di_hash():
    r = client().post("/register", data=DATA)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="alivia@test.id").one()
        assert u.password_hash != "rahasia123" and u.password_hash.startswith("$2b$")
        assert u.peran == "pengguna" and u.aktif


def test_registrasi_email_ganda_ditolak():
    r = client().post("/register", data=DATA)
    assert r.status_code == 400 and "sudah terdaftar" in r.text


def test_registrasi_validasi():
    bad = dict(DATA, email="bukan-email", password="123", password2="456", setuju="")
    bad.pop("setuju")
    r = client().post("/register", data=bad)
    assert r.status_code == 400
    for msg in ["Format email", "minimal 8", "tidak sama", "persetujuan"]:
        assert msg in r.text


def test_login_salah_ditolak():
    assert login(client(), "alivia@test.id", "salah12345").status_code == 401


def test_login_pengguna_dan_akses_admin_ditolak():
    c = client()
    r = login(c, "ALIVIA@test.id", "rahasia123")
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert c.get("/").status_code == 200
    assert c.get("/admin/klaim").status_code == 403


def test_login_admin_diarahkan_ke_halaman_admin():
    seed_admin(["Arzaki", "admin@test.id", "081111111111", "admin12345"])
    c = client()
    r = login(c, "admin@test.id", "admin12345")
    assert r.headers["location"] == "/admin/klaim"
    assert c.get("/admin/klaim").status_code == 200


def test_logout():
    c = client()
    login(c, "alivia@test.id", "rahasia123")
    c.post("/logout")
    assert c.get("/saya").status_code == 303


def test_akun_nonaktif_tidak_bisa_login():
    with SessionLocal() as db:
        db.add(User(nama="X", email="x@test.id", no_kontak="0800000000",
                    password_hash=__import__("app.auth", fromlist=["x"]).hash_password("rahasia123"), aktif=False))
        db.commit()
    r = login(client(), "x@test.id", "rahasia123")
    assert r.status_code == 401 and "dinonaktifkan" in r.text
