"""Eksperimen v4: membandingkan model-model baru untuk image matching LOSTLINK (khusus lingkungan Windows terbaru).

Dibuat untuk: Python 3.14, PyTorch 2.15 (CPU), torchvision 0.29, transformers 5.x, timm 1.0, rembg 2.0.
Aplikasi LOSTLINK tidak diubah; skrip ini hanya untuk pengujian.

Setiap model diuji dalam 2 kondisi:
  asli        foto apa adanya (seperti aplikasi)
  barang      latar dihapus rembg, diisi warna rata-rata ImageNet ("transparan" bagi model), dipotong ke barang
Kondisi "barang" menunjukkan kemampuan mengenali BARANGNYA tanpa bantuan latar yang sama.

Model (pilih lewat argumen; tanpa argumen = paket standar):
  efficientnet_b0     model aplikasi sekarang (pembanding)                       ~20 MB
  dinov2_small        DINOv2 ViT-S/14                                            ~90 MB
  dinov2_base         DINOv2 ViT-B/14                                            ~350 MB
  dinov2_base_reg     DINOv2 ViT-B/14 with registers                             ~350 MB
  siglip2_base        SigLIP 2 base 224 (bagian gambar saja)                     ~400 MB
  vit_b16_swag        ViT-B/16 SWAG (Meta, 3,6 miliar foto) 384 px               ~350 MB
  convnextv2_base     ConvNeXt-V2 base (ImageNet-22k) lewat timm                 ~350 MB
  --- berat (opsional) ---
  dinov2_large        DINOv2 ViT-L/14                                            ~1,2 GB
  regnety_16gf_swag   RegNetY-16GF SWAG 384 px                                   ~330 MB
  siglip2_so400m      SigLIP 2 so400m 384 px                                     ~1,7 GB
Gabungan efficientnet_b0 + dinov2_base dihitung otomatis bila keduanya dijalankan.

Contoh (dari folder yang berisi folder uji_kelayakan):
    python uji_kelayakan\\eksperimen_v4_model.py
    python uji_kelayakan\\eksperimen_v4_model.py dinov2_large siglip2_so400m
Hasil: uji_kelayakan\\hasil_eksperimen_v4_model.csv dan hasil_v4_peringkat.csv (peringkat per barang).
"""
import csv
import os
import sys
import time

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np
from PIL import ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import eksperimen_v3_latar as v3  # noqa: E402  (data, rembg, pengisian latar)

STANDAR = ["efficientnet_b0", "dinov2_small", "dinov2_base", "dinov2_base_reg", "siglip2_base", "vit_b16_swag",
           "convnextv2_base"]
BERAT = ["dinov2_large", "regnety_16gf_swag", "siglip2_so400m"]
HF = {"dinov2_small": "facebook/dinov2-small", "dinov2_base": "facebook/dinov2-base",
      "dinov2_large": "facebook/dinov2-large", "dinov2_base_reg": "facebook/dinov2-with-registers-base",
      "siglip2_base": "google/siglip2-base-patch16-224", "siglip2_so400m": "google/siglip2-so400m-patch14-384"}


# ---------------------------------------------------------------- model -> fungsi(list[PIL]) -> np.ndarray
def muat(nama):
    import torch

    torch.set_grad_enabled(False)

    if nama in ("efficientnet_b0", "vit_b16_swag", "regnety_16gf_swag"):
        from torchvision import models

        if nama == "efficientnet_b0":
            w = models.EfficientNet_B0_Weights.DEFAULT
            net = models.efficientnet_b0(weights=w)
            net.classifier = torch.nn.Identity()
        elif nama == "vit_b16_swag":
            w = models.ViT_B_16_Weights.IMAGENET1K_SWAG_E2E_V1
            net = models.vit_b_16(weights=w)
            net.heads = torch.nn.Identity()
        else:
            w = models.RegNet_Y_16GF_Weights.IMAGENET1K_SWAG_E2E_V1
            net = models.regnet_y_16gf(weights=w)
            net.fc = torch.nn.Identity()
        net.eval()
        pre = w.transforms()
        return lambda imgs: net(torch.stack([pre(i) for i in imgs])).numpy()

    if nama == "convnextv2_base":
        import timm
        from timm.data import create_transform, resolve_data_config

        net = timm.create_model("convnextv2_base.fcmae_ft_in22k_in1k", pretrained=True, num_classes=0).eval()
        pre = create_transform(**resolve_data_config({}, model=net))
        return lambda imgs: net(torch.stack([pre(i) for i in imgs])).numpy()

    from transformers import AutoImageProcessor, AutoModel

    repo = HF[nama]
    proc = AutoImageProcessor.from_pretrained(repo)
    model = AutoModel.from_pretrained(repo).eval()
    if nama.startswith("siglip2"):
        def f(imgs):
            px = proc(images=imgs, return_tensors="pt")
            out = model.get_image_features(**px)
            out = getattr(out, "pooler_output", out)  # transformers 5 bisa mengembalikan objek, bukan tensor
            return out.numpy()
        return f

    def f(imgs):
        px = proc(images=imgs, return_tensors="pt")
        return model(**px).pooler_output.numpy()  # token CLS DINOv2 (setelah layernorm)
    return f


def ekstrak(fungsi, imgs, batch=8):
    """Fitur rata-rata foto asli + cermin, dalam batch kecil agar RAM aman."""
    out = []
    for i in range(0, len(imgs), batch):
        b = imgs[i:i + batch]
        out.append((fungsi(b) + fungsi([ImageOps.mirror(x) for x in b])) / 2)
    return np.concatenate(out)


# ---------------------------------------------------------------- penilaian
def matriks(H, T):
    mu = np.concatenate([H, T]).mean(0, keepdims=True)
    return v3.normal(H, mu) @ v3.normal(T, mu).T


def peringkat(S, hn, tn):
    r = []
    for i, q in enumerate(hn):
        urut = list(np.argsort(-S[i]))
        r.append(next(k for k, j in enumerate(urut, 1) if v3.id_barang(tn[j]) == v3.id_barang(q)))
    return np.array(r)


def ringkas(r, hn):
    return {"top1": (r == 1).mean() * 100, "top5": (r <= 5).mean() * 100, "rata_peringkat": r.mean(),
            "gagal": " ".join(f"{q[:-4]}#{k}" for q, k in zip(hn, r) if k > 1)}


def z(S):
    return (S - S.mean()) / (S.std() + 1e-9)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    pilih = args or STANDAR
    if args and "efficientnet_b0" not in pilih:
        pilih = ["efficientnet_b0"] + pilih  # pembanding selalu ikut
    tidak_dikenal = [m for m in pilih if m not in STANDAR + BERAT]
    if tidak_dikenal:
        sys.exit(f"Model tidak dikenal: {tidak_dikenal}. Pilihan: {STANDAR + BERAT}")

    hn, tn = v3.daftar("hilang"), v3.daftar("temuan")
    print(f"{len(hn)} foto hilang, {len(tn)} foto temuan. Memuat foto ...", flush=True)
    asli = {("hilang", f): v3.buka(os.path.join(v3.DATA, "hilang", f)) for f in hn}
    asli.update({("temuan", f): v3.buka(os.path.join(v3.DATA, "temuan", f)) for f in tn})

    from rembg import new_session

    sesi = new_session("u2net")
    print("Menghapus latar (sekali saja, disimpan di uji_kelayakan\\cache_rgba) ...", flush=True)
    rgba = {k: v3.rgba_tanpa_latar(im, f"{k[0]}/{k[1]}", sesi) for k, im in asli.items()}
    kondisi = {
        "asli": asli,
        "barang": {k: v3.varian_gambar(asli[k], rgba[k], v3.RERATA_IMAGENET)[0] for k in asli},
    }

    rows, ranks, skor = [], {}, {}
    for m in pilih:
        print(f"\nMemuat {m} (unduhan pertama bisa lama) ...", flush=True)
        try:
            fungsi = muat(m)
        except Exception as e:  # model gagal dimuat: lanjut ke model berikutnya
            print(f"  GAGAL memuat {m}: {type(e).__name__}: {e}", flush=True)
            continue
        for kd, gambar in kondisi.items():
            t0 = time.perf_counter()
            H = ekstrak(fungsi, [gambar[("hilang", f)] for f in hn])
            dt = (time.perf_counter() - t0) / len(hn)
            T = ekstrak(fungsi, [gambar[("temuan", f)] for f in tn])
            S = matriks(H, T)
            skor[(m, kd)] = S
            r = peringkat(S, hn, tn)
            ranks[f"{m} {kd}"] = r
            row = ringkas(r, hn)
            row.update(model=m, kondisi=kd, detik_per_foto=dt)
            rows.append(row)
            print(f"  {m:18s} {kd:7s} top1 {row['top1']:5.1f}%  top5 {row['top5']:5.1f}%  "
                  f"rata-peringkat {row['rata_peringkat']:.2f}  {dt:.2f} dtk/foto | gagal: {row['gagal'] or '-'}", flush=True)

    for kd in kondisi:  # gabungan model aplikasi + DINOv2-base
        a, b = ("efficientnet_b0", kd), ("dinov2_base", kd)
        if a in skor and b in skor:
            r = peringkat((z(skor[a]) + z(skor[b])) / 2, hn, tn)
            ranks[f"gabungan_effb0_dinov2b {kd}"] = r
            row = ringkas(r, hn)
            row.update(model="gabungan_effb0_dinov2b", kondisi=kd)
            rows.append(row)
            print(f"  {'gabungan':18s} {kd:7s} top1 {row['top1']:5.1f}%  top5 {row['top5']:5.1f}%  "
                  f"rata-peringkat {row['rata_peringkat']:.2f} | gagal: {row['gagal'] or '-'}", flush=True)

    out = os.path.join(HERE, "hasil_eksperimen_v4_model.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["model", "kondisi", "top1", "top5", "rata_peringkat", "detik_per_foto", "gagal"])
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    out2 = os.path.join(HERE, "hasil_v4_peringkat.csv")
    with open(out2, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["barang"] + list(ranks))
        for i, q in enumerate(hn):
            w.writerow([q[:-4]] + [int(ranks[k][i]) for k in ranks])

    print("\n=== URUTAN (kondisi 'barang' = tanpa bantuan latar) ===")
    for r in sorted(rows, key=lambda x: (x["kondisi"] != "barang", -x["top1"], -x["top5"], x["rata_peringkat"])):
        print(f"  {r['kondisi']:7s} {r['model']:24s} top1 {r['top1']:5.1f}%  top5 {r['top5']:5.1f}%  rata {r['rata_peringkat']:.2f}")
    print(f"\nTersimpan: {out}\n           {out2}")


if __name__ == "__main__":
    main()
