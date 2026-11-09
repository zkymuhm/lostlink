"""Lokasi folder dan batas unggahan."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(os.getenv("LOSTLINK_UPLOAD_DIR", ROOT / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_FOTO_MB = 5
FOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
