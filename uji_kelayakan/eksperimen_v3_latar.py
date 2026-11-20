"""Eksperimen v3: apakah warna pengisi latar memengaruhi hasil setelah latar dihapus?

Pertanyaan: di eksperimen v2 latar yang dihapus diisi abu-abu (128). Bagaimana kalau latarnya
"benar-benar transparan"? Model CNN/ViT selalu butuh gambar RGB penuh, jadi transparansi murni tidak bisa
dimasukkan langsung. Skrip ini menguji pendekatan yang paling mendekati transparan:

  asli                 foto apa adanya (pembanding)
  abu                  latar dihapus, diisi abu-abu 128 (sama dengan v2)
  putih / hitam        latar dihapus, diisi putih / hitam
  transparan           latar dihapus, diisi warna rata-rata ImageNet (124,116,104). Setelah normalisasi model,
                       warna ini menjadi 0 di semua kanal = "tidak ada informasi" bagi model.
  transparan_utuh      sama dengan transparan, tetapi TIDAK dipotong ke barang (ukuran barang tetap seperti foto asli)
  transparan_masker    (EfficientNet-B0) seperti transparan, lalu fitur hanya dirata-rata dari bagian
                       peta fitur yang berisi barang (masked pooling): latar tidak ikut dihitung sama sekali.

Hasil rembg (dengan kanal transparan asli) disimpan di uji_kelayakan/cache_rgba, contoh gambar tiap varian
di uji_kelayakan/hasil_v3_latar/<varian>/, ringkasan di hasil_eksperimen_v3_latar.csv.

Jalankan dari folder proyek (venv aktif):
    python uji_kelayakan/eksperimen_v3_latar.py                 # EfficientNet-B0 saja (±5 menit)
    python uji_kelayakan/eksperimen_v3_latar.py clip dinov2_small   # tambah model lain (model sudah terunduh di v2)
"""
import csv
import os
import sys
import time

import numpy as np
from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(HERE, "cache_rgba")
CONTOH = os.path.join(HERE, "hasil_v3_latar")
UKURAN_MUAT = 640
RERATA_IMAGENET = (124, 116, 104)  # 255 x (0.485, 0.456, 0.406)
ISI = {"abu": (128, 128, 128), "putih": (255, 255, 255), "hitam": (0, 0, 0), "transparan": RERATA_IMAGENET}


# ---------------------------------------------------------------- data
def daftar(sub):
    folder = os.path.join(DATA, sub)
    return sorted(f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg", ".png")) and not f.startswith("."))


def id_barang(f):
    return f[:2] if f[:2].isdigit() else None


def buka(path):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((UKURAN_MUAT, UKURAN_MUAT))
    return img


def rgba_tanpa_latar(img, nama, sesi):
    """Hapus latar dengan rembg (U2-Net) dan simpan hasil RGBA apa adanya (latar transparan)."""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, nama.replace("/", "_") + ".png")
    if os.path.exists(p):
        return Image.open(p).convert("RGBA")
    from rembg import remove

    rgba = remove(img, session=sesi).convert("RGBA")
    rgba.save(p)
    return rgba


def kotak_barang(alpha, w, h):
    ys, xs = np.where(alpha > 128)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    m = int(0.08 * max(x1 - x0, y1 - y0))
    return max(0, x0 - m), max(0, y0 - m), min(w, x1 + m + 1), min(h, y1 + m + 1)


def varian_gambar(asli, rgba, isi, potong=True):
    """Kembalikan (gambar RGB, masker 0..1). Bila barang tidak terdeteksi, pakai foto asli dengan masker penuh."""
    a = np.asarray(rgba)[..., 3]
    if (a > 128).mean() < 0.02:
        return asli, np.ones((asli.height, asli.width), np.float32)
    bg = Image.new("RGB", rgba.size, isi)
    bg.paste(rgba.convert("RGB"), mask=rgba.split()[3])
    masker = Image.fromarray(a)
    if potong:
        box = kotak_barang(a, rgba.width, rgba.height)
        bg, masker = bg.crop(box), masker.crop(box)
    return bg, np.asarray(masker, np.float32) / 255.0


# ---------------------------------------------------------------- model
def siapkan(img, masker=None):
    """Resize 256 + CenterCrop 224 untuk gambar dan maskernya (sama persis dengan aplikasi)."""
    import torch
    from torchvision import transforms

    pre = transforms.Compose([transforms.Resize(256), transforms.CenterCrop(224), transforms.ToTensor(),
                              transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    x = pre(img).unsqueeze(0)
    if masker is None:
        return x, None
    mk = Image.fromarray((masker * 255).astype(np.uint8))
    m = transforms.Compose([transforms.Resize(256), transforms.CenterCrop(224), transforms.ToTensor()])(mk)
    return x, m.unsqueeze(0)  # (1,1,224,224)


def model_efficientnet():
    import torch
    from torchvision import models

    torch.set_grad_enabled(False)
    net = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT).eval()

    def fitur(img, masker=None):
        x, m = siapkan(img, masker)
        out = []
        for xx, mm in ((x, m), (torch.flip(x, dims=[3]), None if m is None else torch.flip(m, dims=[3]))):
            peta = net.features(xx)  # (1,1280,7,7)
            if mm is None:
                v = peta.mean(dim=(2, 3))
            else:
                w = torch.nn.functional.adaptive_avg_pool2d(mm, peta.shape[-2:])  # porsi barang per sel 7x7
                v = (peta * w).sum(dim=(2, 3)) / (w.sum() + 1e-6)
            out.append(v)
        return ((out[0] + out[1]) / 2).flatten().numpy()
    return fitur


def model_lain(nama):
    import torch

    torch.set_grad_enabled(False)
    if nama == "clip":
        from sentence_transformers import SentenceTransformer

        st = SentenceTransformer("clip-ViT-B-32", device="cpu")
        return lambda img, masker=None: ((st.encode([img])[0] + st.encode([ImageOps.mirror(img)])[0]) / 2)
    from transformers import AutoModel

    net = AutoModel.from_pretrained("facebook/dinov2-small").eval()

    def fitur(img, masker=None):
        x, _ = siapkan(img)
        return ((net(pixel_values=x).pooler_output + net(pixel_values=torch.flip(x, dims=[3])).pooler_output) / 2).flatten().numpy()
    return fitur


# ---------------------------------------------------------------- penilaian (sama dengan v2)
def normal(X, mu):
    X = X - mu
    return X / np.linalg.norm(X, axis=1, keepdims=True)


def nilai(H, T, hn, tn):
    mu = np.concatenate([H, T]).mean(0, keepdims=True)
    S = normal(H, mu) @ normal(T, mu).T
    ranks, gagal = [], []
    for i, q in enumerate(hn):
        urut = list(np.argsort(-S[i]))
        r = next(k for k, j in enumerate(urut, 1) if id_barang(tn[j]) == id_barang(q))
        ranks.append(r)
        if r > 1:
            gagal.append(f"{q[:-4]}#{r}")
    ranks = np.array(ranks)
    return {"top1": (ranks == 1).mean() * 100, "top5": (ranks <= 5).mean() * 100,
            "rata_peringkat": ranks.mean(), "gagal": " ".join(gagal)}


def main():
    pilih = ["efficientnet_b0"] + [m for m in sys.argv[1:] if m in ("clip", "dinov2_small")]
    hn, tn = daftar("hilang"), daftar("temuan")
    print(f"{len(hn)} foto hilang, {len(tn)} foto temuan. Memuat foto ...", flush=True)
    asli = {("hilang", f): buka(os.path.join(DATA, "hilang", f)) for f in hn}
    asli.update({("temuan", f): buka(os.path.join(DATA, "temuan", f)) for f in tn})

    from rembg import new_session

    sesi = new_session("u2net")
    print("Menghapus latar dengan rembg (U2-Net), hasil transparan disimpan di uji_kelayakan/cache_rgba ...", flush=True)
    t0 = time.perf_counter()
    rgba = {k: rgba_tanpa_latar(im, f"{k[0]}/{k[1]}", sesi) for k, im in asli.items()}
    print(f"  selesai dalam {time.perf_counter() - t0:.0f} detik", flush=True)

    # gambar + masker untuk setiap varian
    varian = {"asli": {k: (im, None) for k, im in asli.items()}}
    for nama, warna in ISI.items():
        varian[nama] = {k: varian_gambar(asli[k], rgba[k], warna) for k in asli}
    varian["transparan_utuh"] = {k: varian_gambar(asli[k], rgba[k], RERATA_IMAGENET, potong=False) for k in asli}

    for nama, isi in varian.items():  # simpan contoh agar bisa dilihat
        d = os.path.join(CONTOH, nama)
        os.makedirs(d, exist_ok=True)
        for (sub, f), (im, _) in isi.items():
            if id_barang(f):
                kecil = im.copy()
                kecil.thumbnail((360, 360))
                kecil.save(os.path.join(d, f"{sub}_{f[:-4]}.jpg"), quality=85)

    rows = []
    for m in pilih:
        print(f"\nMemuat {m} ...", flush=True)
        fitur = model_efficientnet() if m == "efficientnet_b0" else model_lain(m)
        daftar_varian = list(varian) + (["transparan_masker"] if m == "efficientnet_b0" else [])
        for v in daftar_varian:
            sumber = varian["transparan"] if v == "transparan_masker" else varian[v]
            pakai_masker = v == "transparan_masker"
            H = np.stack([fitur(sumber[("hilang", f)][0], sumber[("hilang", f)][1] if pakai_masker else None) for f in hn])
            T = np.stack([fitur(sumber[("temuan", f)][0], sumber[("temuan", f)][1] if pakai_masker else None) for f in tn])
            r = nilai(H, T, hn, tn)
            r.update(model=m, varian=v)
            rows.append(r)
            print(f"  {m:16s} {v:18s} top1 {r['top1']:5.1f}%  top5 {r['top5']:5.1f}%  rata-peringkat {r['rata_peringkat']:.2f}"
                  f" | gagal: {r['gagal'] or '-'}", flush=True)

    out = os.path.join(HERE, "hasil_eksperimen_v3_latar.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["model", "varian", "top1", "top5", "rata_peringkat", "gagal"])
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    print(f"\nTersimpan: {out}\nContoh gambar tiap varian: {CONTOH}")


if __name__ == "__main__":
    main()
