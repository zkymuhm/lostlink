"""Tabel database sesuai ERD dan kamus data laporan M3 (bagian 3.2)."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

PERAN = ("pengguna", "admin")
JENIS = ("hilang", "temuan")
KATEGORI = ("Tas", "Dompet", "Ponsel", "Kunci", "Lainnya")
STATUS = ("Hilang", "Ditemukan", "Diverifikasi", "Dikembalikan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nama: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    no_kontak: Mapped[str] = mapped_column(String(20))
    peran: Mapped[str] = mapped_column(String(10), default="pengguna")
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    dibuat_pada: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    items: Mapped[list["Item"]] = relationship(back_populates="pelapor")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    jenis: Mapped[str] = mapped_column(String(10))
    kategori: Mapped[str] = mapped_column(String(20))
    deskripsi: Mapped[str] = mapped_column(Text)
    ciri_khusus: Mapped[str] = mapped_column(Text)
    lokasi: Mapped[str] = mapped_column(String(120))
    waktu_kejadian: Mapped[datetime] = mapped_column(DateTime)
    path_foto: Mapped[str] = mapped_column(String(255))
    vektor_fitur: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(String(15), default="Hilang")
    dibuat_pada: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    pelapor: Mapped[User] = relationship(back_populates="items")


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lost_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    found_item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    skor: Mapped[float] = mapped_column(Float)
    peringkat: Mapped[int] = mapped_column(Integer)
    dibuat_pada: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    claimant_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    jawaban_ciri: Mapped[str] = mapped_column(Text)
    hasil: Mapped[str | None] = mapped_column(String(15), nullable=True)
    keputusan_admin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    diputuskan_pada: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
