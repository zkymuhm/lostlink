"""WBS 5.2 — ekstraksi fitur foto dan skor kemiripan (cosine similarity).

Dipindahkan dari uji_kelayakan/lostlink_uji.py (uji ulang 9 Nov 2026: top-5 96%).
Alur sesuai laporan M3 bagian 3.4:
  1. Saat laporan dikirim  -> ekstrak() sekali, vektor 512 angka disimpan di items.vektor_fitur.
  2. Saat rekomendasi dibuka -> top_k() hanya membandingkan vektor tersimpan (cepat, < 5 detik).

LOSTLINK_FAKE_MODEL=1 memakai histogram warna sebagai pengganti ResNet18 (untuk test otomatis
tanpa mengunduh model). Aplikasi biasa selalu memakai ResNet18.
"""
import os
import threading

import numpy as np
from PIL import Image, ImageOps

try:  # dukungan foto HEIC iPhone (opsional)
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # noqa: BLE001
    pass

DIM = 512
_lock = threading.Lock()
_net = None
_pre = None


def fake_mode() -> bool:
    return os.getenv("LOSTLINK_FAKE_MODEL") == "1"


def buka(path) -> Image.Image:
    """Buka foto dan perbaiki rotasi foto HP (EXIF)."""
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def _load():
    global _net, _pre
    with _lock:
        if _net is None:
            import torch
            from torchvision import models

            torch.set_num_threads(max(1, os.cpu_count() or 1))
            weights = models.ResNet18_Weights.DEFAULT
            net = models.resnet18(weights=weights)
            net.fc = torch.nn.Identity()  # buang lapisan klasifikasi -> vektor 512
            net.eval()
            _net, _pre = net, weights.transforms()
    return _net, _pre


def siapkan_model():
    """Muat model di awal agar laporan pertama tidak lambat."""
    if not fake_mode():
        _load()


def _fitur_palsu(img: Image.Image) -> np.ndarray:
    small = np.asarray(img.resize((64, 64)), dtype=np.int64) // 32  # 8 tingkat per kanal
    idx = small[..., 0] * 64 + small[..., 1] * 8 + small[..., 2]
    return np.bincount(idx.ravel(), minlength=DIM).astype(np.float32)


def ekstrak(path) -> np.ndarray:
    """Foto -> vektor fitur 512 angka yang sudah dinormalisasi (panjang 1)."""
    img = buka(path)
    if fake_mode():
        v = _fitur_palsu(img)
    else:
        import torch

        net, pre = _load()
        with torch.inference_mode():
            v = net(pre(img).unsqueeze(0)).flatten().numpy().astype(np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n else v


def ke_bytes(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def dari_bytes(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def top_k(query: bytes, kandidat: list[tuple[int, bytes]], k: int = 5) -> list[tuple[int, float]]:
    """Urutkan kandidat dari skor cosine tertinggi. kandidat = [(item_id, vektor_bytes), ...]."""
    kandidat = [(i, b) for i, b in kandidat if b]
    if not kandidat or not query:
        return []
    q = dari_bytes(query)
    M = np.stack([dari_bytes(b) for _, b in kandidat])
    skor = M @ q
    urut = np.argsort(-skor)[:k]
    return [(kandidat[j][0], float(skor[j])) for j in urut]
