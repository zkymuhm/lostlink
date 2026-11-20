"""WBS 5.2 — ekstraksi fitur foto dan skor kemiripan (cosine similarity).

Model bawaan sejak 20 Nov 2026: SigLIP 2 base (google/siglip2-base-patch16-224), bagian gambar saja.
  uji_kelayakan/eksperimen_v4_model.py, 30 pasang + 27 pengecoh, sama di Mac dan Windows:
    foto asli           top-1 100%, top-5 100%   (EfficientNet-B0: 90%, 100%)
    latar dihapus       top-1 93,3%, top-5 100%  (EfficientNet-B0: 76,7%, 96,7%)  -> lebih mengenali barang, bukan latar
    0,34 detik/foto di Mac (EfficientNet-B0: 0,07)
  Model sebelumnya tetap bisa dipakai: LOSTLINK_MODEL=efficientnet_b0 (atau resnet18), lalu python -m app.perbarui_model.
Setiap foto: rata-rata fitur foto asli dan foto dicerminkan, dikurangi vektor rata-rata, dinormalisasi.
Alur sesuai laporan M3 bagian 3.4:
  1. Saat laporan dikirim  -> ekstrak() sekali, vektor fitur disimpan di items.vektor_fitur.
  2. Saat rekomendasi dibuka -> top_k() hanya membandingkan vektor tersimpan (cepat, < 5 detik).

Vektor rata-rata ("center") disimpan di app/data/rerata_<model>.npy dan batas persen tampilan di
app/data/kalibrasi_<model>.json. Keduanya dibuat dengan
    python -m app.perbarui_model
yang sekaligus menghitung ulang vektor semua laporan lama di database.

LOSTLINK_FAKE_MODEL=1 memakai histogram warna sebagai pengganti model (untuk test otomatis
tanpa mengunduh model).
"""
import json
import os
import threading
from datetime import timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:  # dukungan foto HEIC iPhone (opsional)
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # noqa: BLE001
    pass

MODEL = os.getenv("LOSTLINK_MODEL", "siglip2_base")
MODEL_HF = {"siglip2_base": "google/siglip2-base-patch16-224"}  # model Hugging Face (bagian gambar saja)
DATA_DIR = Path(__file__).parent / "data"
RERATA_PATH = DATA_DIR / f"rerata_{MODEL}.npy"
KALIBRASI_PATH = DATA_DIR / f"kalibrasi_{MODEL}.json"
DIM_PALSU = 512
_lock = threading.Lock()
_net = None
_pre = None
_rerata = None


def fake_mode() -> bool:
    return os.getenv("LOSTLINK_FAKE_MODEL") == "1"


def buka(path) -> Image.Image:
    """Buka foto dan perbaiki rotasi foto HP (EXIF)."""
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def _load_hf(repo: str):
    """Model gambar Hugging Face (SigLIP 2) -> (fungsi list[PIL] -> tensor fitur, None)."""
    from transformers import AutoConfig, AutoImageProcessor

    if AutoConfig.from_pretrained(repo).model_type == "siglip2":
        from transformers import Siglip2VisionModel as Visi
    else:
        from transformers import SiglipVisionModel as Visi
    net = Visi.from_pretrained(repo).eval()  # tanpa bagian teks: lebih hemat memori
    proc = AutoImageProcessor.from_pretrained(repo)

    def jalankan(imgs):
        return net(**proc(images=imgs, return_tensors="pt")).pooler_output  # rangkuman attention pooling

    return jalankan, None


def _load():
    global _net, _pre, _rerata
    with _lock:
        if _net is None:
            import torch
            from torchvision import models, transforms

            torch.set_num_threads(max(1, os.cpu_count() or 1))
            if MODEL in MODEL_HF:
                _net, _pre = _load_hf(MODEL_HF[MODEL])
                _rerata = np.load(RERATA_PATH) if RERATA_PATH.exists() else None
                return _net, _pre
            if MODEL == "resnet18":
                net = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
                net.fc = torch.nn.Identity()
            else:
                net = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT)
                net.classifier = torch.nn.Identity()  # buang lapisan klasifikasi -> vektor 1280
            net.eval()
            # sama persis dengan pra-proses "crop" di eksperimen
            _pre = transforms.Compose([transforms.Resize(256), transforms.CenterCrop(224), transforms.ToTensor(),
                                       transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
            _net = net
            _rerata = np.load(RERATA_PATH) if RERATA_PATH.exists() else None
    return _net, _pre


def siapkan_model():
    """Muat model di awal agar laporan pertama tidak lambat."""
    if not fake_mode():
        _load()
        if _rerata is None or not KALIBRASI_PATH.exists():
            print(f"[LOSTLINK] Model {MODEL}: rerata/kalibrasi belum ada. Jalankan: python -m app.perbarui_model")


def _fitur_palsu(img: Image.Image) -> np.ndarray:
    small = np.asarray(img.resize((64, 64)), dtype=np.int64) // 32  # 8 tingkat per kanal
    idx = small[..., 0] * 64 + small[..., 1] * 8 + small[..., 2]
    return np.bincount(idx.ravel(), minlength=DIM_PALSU).astype(np.float32)


def fitur_mentah(img: Image.Image) -> np.ndarray:
    """Fitur sebelum dikurangi rata-rata: rata-rata foto asli dan foto dicerminkan."""
    import torch

    net, pre = _load()
    with torch.inference_mode():
        if pre is None:  # model Hugging Face: pra-proses di dalam fungsi
            v = net([img, ImageOps.mirror(img)]).mean(dim=0)
        else:
            x = pre(img).unsqueeze(0)
            v = (net(x) + net(torch.flip(x, dims=[3]))) / 2
    return v.flatten().numpy().astype(np.float32)


def _normal(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return (v / n if n else v).astype(np.float32)


def ekstrak(path) -> np.ndarray:
    """Foto -> vektor fitur yang sudah dikurangi rata-rata dan dinormalisasi (panjang 1)."""
    img = buka(path)
    if fake_mode():
        return _normal(_fitur_palsu(img))
    v = fitur_mentah(img)
    if _rerata is not None and _rerata.shape == v.shape:
        v = v - _rerata
    return _normal(v)


def ke_bytes(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def dari_bytes(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


# --- Skor untuk tampilan -------------------------------------------------------------------
# Cosine mentah CNN tidak pernah mendekati 0 untuk barang yang berbeda: fitur setelah ReLU
# selalu positif, jadi dua foto benda apa pun sudah "searah" sekitar 0.4-0.6. Angka itu benar
# untuk mengurutkan, tetapi menyesatkan bila ditampilkan sebagai persen ("botol vs dompet 55%").
# Maka skor mentah tetap disimpan dan dipakai mengurutkan, sedangkan yang ditampilkan dipetakan:
#   SKOR_DASAR (hampir semua barang berbeda di bawah ini) -> 0%
#   SKOR_PENUH (skor foto pasangan yang sangat cocok) -> 100%
# Setelah dikurangi rata-rata, barang berbeda rata-rata berskor -0,02 dan 95% di bawah 0,16,
# sedangkan pasangan yang benar rata-rata 0,50 (hasil_eksperimen.csv, efficientnet_b0 crop flip center).
# Maka 0,16 -> 0% dan 0,60 -> 100%: pasangan benar umumnya tampil sekitar 75-80%, barang lain dekat 0%.
# Batas ini berbeda untuk setiap model, jadi dihitung ulang oleh perbarui_model dari 30 pasang foto uji
# (SKOR_DASAR = persentil 95 pasangan salah; SKOR_PENUH dipilih agar rata-rata pasangan benar tampil 77%)
# dan disimpan di app/data/kalibrasi_<model>.json. Angka di bawah adalah nilai EfficientNet-B0 sebagai cadangan.
SKOR_DASAR, SKOR_PENUH = 0.16, 0.60
if not fake_mode() and KALIBRASI_PATH.exists():
    try:
        _k = json.loads(KALIBRASI_PATH.read_text())
        SKOR_DASAR, SKOR_PENUH = float(_k["skor_dasar"]), float(_k["skor_penuh"])
    except Exception:  # noqa: BLE001
        print(f"[LOSTLINK] {KALIBRASI_PATH.name} tidak terbaca, memakai batas bawaan")
SKOR_DASAR = float(os.getenv("LOSTLINK_SKOR_DASAR", SKOR_DASAR))
SKOR_PENUH = float(os.getenv("LOSTLINK_SKOR_PENUH", SKOR_PENUH))
BATAS_TINGGI, BATAS_SEDANG = 60, 30  # dalam persen tampilan
# Kandidat di bawah ini tidak ditampilkan ke pengguna (tetap dihitung untuk top-5 dan uji akurasi).
# 15% tampilan = skor 0,23: di atas hampir semua pasangan salah (p95 0,16), di bawah pasangan benar (rata-rata 0,50).
BATAS_TAMPIL = int(os.getenv("LOSTLINK_BATAS_TAMPIL", "15"))


def persen(skor: float) -> int:
    """Skor cosine mentah -> persen kemiripan yang wajar dibaca pengguna (0-100)."""
    x = (skor - SKOR_DASAR) / (SKOR_PENUH - SKOR_DASAR)
    return int(round(min(max(x, 0.0), 1.0) * 100))


def tingkat(skor: float) -> tuple[str, str]:
    """(label, kelas css) untuk skor cosine mentah."""
    p = persen(skor)
    if p >= BATAS_TINGGI:
        return "Sangat mirip", "tinggi"
    if p >= BATAS_SEDANG:
        return "Cukup mirip", "sedang"
    return "Kurang mirip", "rendah"


# --- Data pendukung --------------------------------------------------------------------------
# Foto tetap penentu utama. Kategori, waktu, lokasi, dan nama/ciri-ciri hanya MENAMBAH skor
# (tidak pernah mengurangi atau menyaring), jadi data yang salah isi tidak bisa menyembunyikan
# barang yang fotonya mirip. Total tambahan paling besar 0,13; selisih skor foto pasangan benar
# dan salah sekitar 0,50 (hasil_eksperimen.csv), jadi data hanya menggeser urutan barang yang
# fotonya sama-sama mirip.
# 16 Nov 2026: tambahan lokasi dan teks DIMATIKAN (0). Pencocokan "kata yang sama" tidak paham sinonim
# ("TWS" vs "earbud") dan bisa bias ("botol hijau" vs "tas hijau"). Akan diganti pencocokan makna
# (model teks multibahasa) bila terbukti akurat di uji_kelayakan/eksperimen_v2.py.
BONUS_KATEGORI, BONUS_WAKTU = 0.03, 0.02
BONUS_LOKASI = float(os.getenv("LOSTLINK_BONUS_LOKASI", "0"))
BONUS_TEKS = float(os.getenv("LOSTLINK_BONUS_TEKS", "0"))
KATA_UMUM = {"barang", "yang", "dan", "dengan", "ada", "di", "ke", "dari", "dekat", "jalan", "jl", "depan", "belakang",
             "samping", "lantai", "nomor", "nomer", "no", "warna", "ini", "itu", "untuk", "atau", "saya", "milik", "agak",
             "tas", "dompet", "ponsel", "kunci", "lainnya"}


def kata(*teks) -> set[str]:
    import re

    return {w for t in teks if t for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) >= 3 and w not in KATA_UMUM}


def _irisan(a: set, b: set) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def skor_gabungan(hilang, temuan, skor_foto: float) -> tuple[float, list[str]]:
    """(skor untuk mengurutkan, alasan yang ditampilkan). hilang/temuan = objek Item."""
    skor, alasan = skor_foto, []
    if hilang.kategori == temuan.kategori:
        skor += BONUS_KATEGORI
        alasan.append("kategori sama")
    if hilang.waktu_diketahui and temuan.waktu_kejadian >= hilang.waktu_kejadian - timedelta(days=1):
        skor += BONUS_WAKTU
        alasan.append("ditemukan setelah hilang")
    lok_h, lok_t = kata(hilang.lokasi), kata(temuan.lokasi)
    if BONUS_LOKASI and _irisan(lok_h, lok_t):
        skor += BONUS_LOKASI * _irisan(lok_h, lok_t)
        alasan.append("lokasi mirip")
    # lokasi dibuang dari teks agar judul otomatis "Barang tas di Stasiun" tidak dihitung dua kali
    teks_h = kata(hilang.nama, hilang.deskripsi) - lok_h
    teks_t = kata(temuan.nama, temuan.deskripsi) - lok_t
    if BONUS_TEKS and _irisan(teks_h, teks_t):
        skor += BONUS_TEKS * _irisan(teks_h, teks_t)
        alasan.append("nama/ciri mirip")
    return skor, alasan


def skor_foto_semua(query: bytes, kandidat: list[tuple[int, bytes]]) -> dict[int, float]:
    """Skor cosine foto untuk setiap kandidat {item_id: skor}."""
    kandidat = [(i, b) for i, b in kandidat if b and query and len(b) == len(query)]
    if not kandidat:
        return {}
    skor = np.stack([dari_bytes(b) for _, b in kandidat]) @ dari_bytes(query)
    return {kandidat[j][0]: float(skor[j]) for j in range(len(kandidat))}


def top_k(query: bytes, kandidat: list[tuple[int, bytes]], k: int = 5) -> list[tuple[int, float]]:
    """Urutkan kandidat dari skor cosine tertinggi. kandidat = [(item_id, vektor_bytes), ...]."""
    # lewati vektor dari model lama (panjang berbeda) sampai dihitung ulang dengan perbarui_model
    kandidat = [(i, b) for i, b in kandidat if b and query and len(b) == len(query)]
    if not kandidat:
        return []
    q = dari_bytes(query)
    M = np.stack([dari_bytes(b) for _, b in kandidat])
    skor = M @ q
    urut = np.argsort(-skor)[:k]
    return [(kandidat[j][0], float(skor[j])) for j in urut]
