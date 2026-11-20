"""Eksperimen peningkatan akurasi image matching LOSTLINK.

Membandingkan beberapa model dan cara pra-proses pada dataset 30 pasang + 27 pengecoh
(uji_kelayakan/data). Tidak mengubah aplikasi; hanya mencetak tabel perbandingan dan
menyimpan hasil_eksperimen.csv.

Jalankan dari folder proyek (venv aktif):
    python uji_kelayakan/eksperimen_model.py

Varian yang diuji:
  model : resnet18 (sekarang), resnet50, efficientnet_b0, convnext_tiny
  pra   : crop  = resize 256 lalu potong tengah 224 (bawaan torchvision, bisa memotong barang)
          utuh  = seluruh foto dipadatkan ke kotak 224x224 dengan bantalan, tidak ada yang terpotong
  flip  : rata-rata fitur foto asli dan foto dicerminkan (test-time augmentation)
  center: fitur dikurangi rata-rata seluruh fitur galeri sebelum dinormalisasi
          (membuat skor barang yang tidak berhubungan mendekati 0, bukan 50-60%)
"""
import csv
import os
import sys
import time

import numpy as np
import torch
from PIL import Image, ImageOps
from torchvision import models, transforms

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
torch.set_grad_enabled(False)
torch.set_num_threads(max(1, os.cpu_count() or 1))

MODELS = {
    "resnet18": (models.resnet18, models.ResNet18_Weights.DEFAULT, "fc"),
    "resnet50": (models.resnet50, models.ResNet50_Weights.DEFAULT, "fc"),
    "efficientnet_b0": (models.efficientnet_b0, models.EfficientNet_B0_Weights.DEFAULT, "classifier"),
    "convnext_tiny": (models.convnext_tiny, models.ConvNeXt_Tiny_Weights.DEFAULT, "classifier2"),
}
NORM = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
PRA = {
    "crop": transforms.Compose([transforms.Resize(256), transforms.CenterCrop(224), transforms.ToTensor(), NORM]),
    "utuh": None,  # diisi fungsi pad_square di bawah
}


def buka(p):
    return ImageOps.exif_transpose(Image.open(p)).convert("RGB")


def pad_square(img, size=224):
    img = img.copy()
    img.thumbnail((size, size))
    bg = Image.new("RGB", (size, size), tuple(int(c) for c in np.asarray(img).reshape(-1, 3).mean(0)))
    bg.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
    return NORM(transforms.functional.to_tensor(bg))


def siapkan(nama):
    fn, w, head = MODELS[nama]
    net = fn(weights=w)
    if head == "fc":
        net.fc = torch.nn.Identity()
    elif head == "classifier":
        net.classifier = torch.nn.Identity()
    else:  # convnext: buang hanya lapisan linear terakhir, pertahankan LayerNorm + Flatten
        net.classifier[2] = torch.nn.Identity()
    return net.eval()


def daftar(folder):
    return sorted(f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg", ".png")) and not f.startswith("."))


def id_barang(f):
    return f[:2] if f[:2].isdigit() else None


def fitur(net, imgs, pra, flip):
    out, waktu = [], []
    for img in imgs:
        t0 = time.perf_counter()
        x = pad_square(img) if pra == "utuh" else PRA["crop"](img)
        v = net(x.unsqueeze(0)).flatten()
        if flip:
            v = (v + net(torch.flip(x, dims=[2]).unsqueeze(0)).flatten()) / 2
        out.append(v.numpy())
        waktu.append(time.perf_counter() - t0)
    return np.stack(out), float(np.mean(waktu))


def nilai(H, T, hn, tn, center):
    if center:
        mu = np.concatenate([H, T]).mean(0, keepdims=True)
        H, T = H - mu, T - mu
    H = H / np.linalg.norm(H, axis=1, keepdims=True)
    T = T / np.linalg.norm(T, axis=1, keepdims=True)
    S = H @ T.T
    ranks, pos, neg_top, gagal = [], [], [], []
    for i, q in enumerate(hn):
        urut = np.argsort(-S[i])
        benar = [j for j in urut if id_barang(tn[j]) == id_barang(q)]
        r = list(urut).index(benar[0]) + 1
        ranks.append(r)
        pos.append(S[i, benar[0]])
        neg_top.append(max(S[i, j] for j in urut if id_barang(tn[j]) != id_barang(q)))
        if r > 1:
            gagal.append(f"{q[:-4]}#{r}")
    ranks = np.array(ranks)
    semua_neg = [S[i, j] for i in range(len(hn)) for j in range(len(tn)) if id_barang(tn[j]) != id_barang(hn[i])]
    return {
        "top1": (ranks == 1).mean() * 100, "top5": (ranks <= 5).mean() * 100, "rata_peringkat": ranks.mean(),
        "skor_benar": np.mean(pos) * 100, "skor_salah_rata": np.mean(semua_neg) * 100,
        "skor_salah_tertinggi": np.mean(neg_top) * 100, "p95_salah": np.percentile(semua_neg, 95) * 100,
        "gagal": " ".join(gagal),
    }


def main():
    pilih = sys.argv[1:] or list(MODELS)
    hn, tn = daftar(os.path.join(DATA, "hilang")), daftar(os.path.join(DATA, "temuan"))
    Hi = [buka(os.path.join(DATA, "hilang", f)) for f in hn]
    Ti = [buka(os.path.join(DATA, "temuan", f)) for f in tn]
    print(f"{len(hn)} foto hilang, {len(tn)} foto temuan\n")
    rows = []
    for m in pilih:
        print(f"Memuat {m} ...", flush=True)
        net = siapkan(m)
        for pra in ("crop", "utuh"):
            for flip in (False, True):
                H, t1 = fitur(net, Hi, pra, flip)
                T, _ = fitur(net, Ti, pra, flip)
                for center in (False, True):
                    r = nilai(H, T, hn, tn, center)
                    r.update(model=m, pra=pra, flip="ya" if flip else "tidak", center="ya" if center else "tidak", detik_per_foto=t1)
                    rows.append(r)
                    print(f"  {m:16s} {pra:4s} flip={r['flip']:5s} center={r['center']:5s} | top1 {r['top1']:5.1f}%  top5 {r['top5']:5.1f}%  "
                          f"rata-peringkat {r['rata_peringkat']:.2f}  {t1:.2f} dtk | benar {r['skor_benar']:.0f}%  salah-rata {r['skor_salah_rata']:.0f}%  "
                          f"| gagal: {r['gagal'] or '-'}", flush=True)
    kolom = ["model", "pra", "flip", "center", "top1", "top5", "rata_peringkat", "detik_per_foto", "skor_benar",
             "skor_salah_rata", "skor_salah_tertinggi", "p95_salah", "gagal"]
    out = os.path.join(HERE, "hasil_eksperimen.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=kolom, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
    terbaik = sorted(rows, key=lambda r: (-r["top5"], -r["top1"], r["rata_peringkat"], r["detik_per_foto"]))[:5]
    print("\n=== 5 VARIAN TERBAIK ===")
    for r in terbaik:
        print(f"{r['model']:16s} pra={r['pra']} flip={r['flip']} center={r['center']} -> top1 {r['top1']:.1f}%  top5 {r['top5']:.1f}%  "
              f"{r['detik_per_foto']:.2f} dtk/foto | gagal: {r['gagal'] or '-'}")
    print(f"\nTersimpan: {out}")


if __name__ == "__main__":
    main()
