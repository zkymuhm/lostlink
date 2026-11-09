"""Membuat akun admin pertama.

Pemakaian:
    python -m app.seed_admin "Nama Admin" admin@lostlink.local 08123456789 katasandi123
"""
import sys

from sqlalchemy import select

from .auth import hash_password
from .database import Base, SessionLocal, engine
from .models import User


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 1
    nama, email, kontak, sandi = argv
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.lower()))
        if user:
            user.peran, user.aktif = "admin", True
            print(f"{email} sudah ada; peran diubah menjadi admin.")
        else:
            db.add(User(nama=nama, email=email.lower(), no_kontak=kontak, password_hash=hash_password(sandi), peran="admin"))
            print(f"Admin {email} dibuat.")
        db.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
