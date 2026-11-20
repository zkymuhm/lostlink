"""Koneksi SQLite (WBS 3.2). Lokasi database bisa diganti lewat env DATABASE_URL."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lostlink.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def pastikan_kolom():
    """Migrasi kecil tanpa menghapus data: tambah kolom baru ke database lama (SQLite)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    tambah = {"items": {"nama": "VARCHAR(60) DEFAULT ''"},
              "verifications": {"keterangan": "TEXT", "bukti_foto": "VARCHAR(255)"}}
    for tabel, kolom in tambah.items():
        if tabel not in insp.get_table_names():
            continue
        ada = {c["name"] for c in insp.get_columns(tabel)}
        with engine.begin() as con:
            for nama, tipe in kolom.items():
                if nama not in ada:
                    con.execute(text(f"ALTER TABLE {tabel} ADD COLUMN {nama} {tipe}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
