"""Simpan foto unggahan (dipakai untuk foto bukti klaim)."""
import uuid
from pathlib import Path

from fastapi import UploadFile

from . import matching
from .config import FOTO_EXT, MAX_FOTO_MB, UPLOAD_DIR


async def simpan(upload: UploadFile | None, awalan: str = "", potong: str = "") -> tuple[str | None, str | None]:
    """(nama_file, None) bila berhasil, (None, pesan) bila gagal, (None, None) bila tidak ada file."""
    if upload is None or not upload.filename:
        return None, None
    data = await upload.read()
    if not data:
        return None, None
    ext = Path(upload.filename).suffix.lower()
    if ext not in FOTO_EXT:
        return None, f"File “{upload.filename}” bukan format foto yang didukung. Pakai JPG, PNG, WEBP, atau HEIC."
    if len(data) > MAX_FOTO_MB * 1024 * 1024:
        return None, f"Fotonya {len(data) / 1024 / 1024:.1f} MB, lebih dari batas {MAX_FOTO_MB} MB."
    raw = UPLOAD_DIR / f"raw_{uuid.uuid4().hex}{ext}"
    raw.write_bytes(data)
    try:
        img = matching.buka(raw)
        if potong:
            from .routers.laporan import _potong

            img = _potong(img, potong)
        img.thumbnail((1600, 1600))
        nama = f"{awalan}{uuid.uuid4().hex}.jpg"
        img.save(UPLOAD_DIR / nama, "JPEG", quality=88)
        return nama, None
    except Exception:  # noqa: BLE001
        return None, "File ini sepertinya bukan foto atau rusak. Coba pilih foto lain."
    finally:
        raw.unlink(missing_ok=True)
