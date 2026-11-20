"""Eksperimen v2: model foto yang lebih tahan beda tempat + pencocokan keterangan berdasarkan makna.

Dataset: uji_kelayakan/data (30 pasang + 27 pengecoh). Tidak mengubah aplikasi.

Varian foto (semua memakai rata-rata foto asli + cermin dan dikurangi rata-rata):
  efficientnet_b0 : model aplikasi sekarang (pembanding)
  dinov2_small    : DINOv2 ViT-S/14, dilatih untuk mengenali benda yang sama dari sudut/tempat berbeda
  clip            : CLIP ViT-B/32, foto dan teks berada di "ruang makna" yang sama
  ... x latar     : asli, atau tanpa_latar (latar dihapus dengan rembg, barang dipotong lalu diberi latar abu-abu)

Varian keterangan (data/keterangan.csv), diuji dalam 2 skenario cara pemilik menulis:
  mirip : kata-kata pemilik hampir sama dengan penemu ("Case earbud biru muda pakai tali")
  beda  : makna sama, kata berbeda / sinonim ("TWS warna biru pastel kotaknya bulat")
  teks_teks  : keterangan pemilik vs keterangan penemu (model teks multibahasa, paham bahasa Indonesia)
  teks_foto  : keterangan pemilik vs FOTO barang temuan (CLIP multibahasa)
  gabungan   : (1-w) x skor foto + w x skor keterangan, w = 0,1 ... 0,5

Pasang dulu (sekali, di venv proyek):
    pip install "sentence-transformers==3.3.1" "transformers==4.46.3" "numpy<2" torch==2.2.2 torchvision==0.17.2
    pip install "rembg[cpu]" "numpy<2" torch==2.2.2      # opsional; bila gagal, varian tanpa_latar dilewati
Jalankan dari folder proyek:
    python uji_kelayakan/eksperimen_v2.py
Unduhan model pertama kali: DINOv2 ~90 MB, CLIP ~600 MB, CLIP multibahasa ~540 MB, rembg ~170 MB.
"""
import csv
import os
import sys
import time

import numpy as np
from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(HERE, "cache_tanpa_latar")
UKURAN_MUAT = 640  # foto asli sampai 6 MB; diperkecil dulu agar cepat


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


def tanpa_latar(img, nama, sesi):
    """Hapus latar dengan rembg, potong ke barangnya, beri latar abu-abu. Hasil disimpan di cache."""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, nama.replace("/", "_") + ".png")
    if os.path.exists(p):
        return Image.open(p).convert("RGB")
    from rembg import remove

    rgba = remove(img, session=sesi)
    a = np.asarray(rgba)[..., 3]
    if (a > 128).mean() < 0.02:  # barang tidak terdeteksi -> pakai foto asli
        out = img
    else:
        ys, xs = np.where(a > 128)
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        m = int(0.08 * max(x1 - x0, y1 - y0))
        box = (max(0, x0 - m), max(0, y0 - m), min(img.width, x1 + m), min(img.height, y1 + m))
        bg = Image.new("RGB", rgba.size, (128, 128, 128))
        bg.paste(rgba, mask=rgba.split()[3])
        out = bg.crop(box)
    out.save(p)
    return out


def baca_keterangan():
    """{file: baris}. Kolom: keterangan (pemilik skenario MIRIP / penemu), keterangan_beda (pemilik skenario BEDA)."""
    p = os.path.join(DATA, "keterangan.csv")
    if not os.path.exists(p):
        return {}
    with open(p, newline="", encoding="utf-8-sig") as f:
        return {r["file"]: r for r in csv.DictReader(f)}


# ---------------------------------------------------------------- model
def model_foto(nama):
    """Kembalikan fungsi: list[PIL] -> np.ndarray (fitur mentah, rata-rata asli + cermin)."""
    import torch
    from torchvision import transforms

    torch.set_grad_enabled(False)
    pre = transforms.Compose([transforms.Resize(256), transforms.CenterCrop(224), transforms.ToTensor(),
                              transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    if nama == "clip":
        from sentence_transformers import SentenceTransformer

        st = SentenceTransformer("clip-ViT-B-32", device="cpu")

        def f(imgs):
            a = st.encode(imgs, batch_size=16, convert_to_numpy=True)
            b = st.encode([ImageOps.mirror(i) for i in imgs], batch_size=16, convert_to_numpy=True)
            return (a + b) / 2
        return f
    if nama == "dinov2_small":
        from transformers import AutoModel

        net = AutoModel.from_pretrained("facebook/dinov2-small").eval()

        def jalankan(x):
            return net(pixel_values=x).pooler_output
    else:
        from torchvision import models

        net = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT)
        net.classifier = torch.nn.Identity()
        net.eval()
        jalankan = net

    def f(imgs):
        out = []
        for img in imgs:
            x = pre(img).unsqueeze(0)
            out.append(((jalankan(x) + jalankan(torch.flip(x, dims=[3]))) / 2).flatten().numpy())
        return np.stack(out)
    return f


# ---------------------------------------------------------------- penilaian
def normal(X, center=True, mu=None):
    if center:
        X = X - (X.mean(0, keepdims=True) if mu is None else mu)
    return X / np.linalg.norm(X, axis=1, keepdims=True)


def matriks_foto(H, T):
    mu = np.concatenate([H, T]).mean(0, keepdims=True)
    return normal(H, mu=mu) @ normal(T, mu=mu).T


def z(S, ada=None):
    """Standarkan skor agar foto dan teks bisa dijumlah. Pasangan tanpa keterangan diberi 0 (netral)."""
    vals = S[ada] if ada is not None else S
    Z = (S - vals.mean()) / (vals.std() + 1e-9)
    if ada is not None:
        Z = np.where(ada, Z, 0.0)
    return Z


def nilai(S, hn, tn):
    ranks, gagal, pos, neg = [], [], [], []
    for i, q in enumerate(hn):
        urut = list(np.argsort(-S[i]))
        r = next(k for k, j in enumerate(urut, 1) if id_barang(tn[j]) == id_barang(q))
        ranks.append(r)
        if r > 1:
            gagal.append(f"{q[:-4]}#{r}")
        for j in range(len(tn)):
            (pos if id_barang(tn[j]) == id_barang(q) else neg).append(S[i, j])
    ranks = np.array(ranks)
    return {"top1": (ranks == 1).mean() * 100, "top5": (ranks <= 5).mean() * 100, "rata_peringkat": ranks.mean(),
            "skor_benar": float(np.mean(pos)), "skor_salah_rata": float(np.mean(neg)), "p95_salah": float(np.percentile(neg, 95)),
            "gagal": " ".join(gagal)}


def cetak(r):
    print(f"  {r['varian']:44s} top1 {r['top1']:5.1f}%  top5 {r['top5']:5.1f}%  rata-peringkat {r['rata_peringkat']:.2f}"
          f"{'  ' + format(r['detik_per_foto'], '.2f') + ' dtk' if r.get('detik_per_foto') else ''} | gagal: {r['gagal'] or '-'}", flush=True)


# ---------------------------------------------------------------- utama
def main():
    pilih = sys.argv[1:] or ["efficientnet_b0", "dinov2_small", "clip"]
    hn, tn = daftar("hilang"), daftar("temuan")
    print(f"{len(hn)} foto hilang, {len(tn)} foto temuan. Memuat foto ...", flush=True)
    foto = {"asli": ([buka(os.path.join(DATA, "hilang", f)) for f in hn], [buka(os.path.join(DATA, "temuan", f)) for f in tn])}

    try:
        from rembg import new_session

        sesi = new_session("u2net")
        print("Menghapus latar foto (sekali saja, disimpan di uji_kelayakan/cache_tanpa_latar) ...", flush=True)
        foto["tanpa_latar"] = ([tanpa_latar(im, "hilang/" + f, sesi) for im, f in zip(foto["asli"][0], hn)],
                               [tanpa_latar(im, "temuan/" + f, sesi) for im, f in zip(foto["asli"][1], tn)])
    except ImportError:
        print("rembg belum terpasang: varian tanpa_latar dilewati.")

    rows, skor_foto = [], {}
    for m in pilih:
        print(f"\nMemuat {m} ...", flush=True)
        f = model_foto(m)
        for latar, (Hi, Ti) in foto.items():
            t0 = time.perf_counter()
            H = f(Hi)
            dt = (time.perf_counter() - t0) / len(Hi)
            T = f(Ti)
            S = matriks_foto(H, T)
            skor_foto[(m, latar)] = S
            r = nilai(S, hn, tn)
            r.update(varian=f"foto {m} {latar}", detik_per_foto=dt)
            rows.append(r)
            cetak(r)
            if m == "clip" and latar == "asli":
                T_clip = normal(T, center=False)

    ket = baca_keterangan()
    kt = [(ket.get("temuan/" + f) or {}).get("keterangan", "").strip() for f in tn]
    skenario = {"mirip": "keterangan", "beda": "keterangan_beda"}  # cara pemilik menulis dibanding penemu
    if sum(map(bool, kt)) < 10:
        print("\nKeterangan belum diisi (data/keterangan.csv): uji teks dilewati.")
        skenario = {}
    else:
        print("\nMemuat model teks multibahasa (paham bahasa Indonesia) ...", flush=True)
        from sentence_transformers import SentenceTransformer

        st = SentenceTransformer("sentence-transformers/clip-ViT-B-32-multilingual-v1", device="cpu")
        ET = normal(st.encode([k or "-" for k in kt], convert_to_numpy=True), center=False)
        ada_t = np.array([bool(k) for k in kt])[None, :]
    for nama_sk, kolom_sk in skenario.items():
        kh = [(ket.get("hilang/" + f) or {}).get(kolom_sk, "").strip() for f in hn]
        if sum(map(bool, kh)) < 10:
            continue
        print(f"\n--- Skenario keterangan {nama_sk.upper()}: {sum(map(bool, kh))}/{len(kh)} pemilik, {sum(map(bool, kt))}/{len(kt)} penemu ---",
              flush=True)
        EH = normal(st.encode([k or "-" for k in kh], convert_to_numpy=True), center=False)
        ada_h = np.array([bool(k) for k in kh])[:, None]
        teks = {"teks_teks": (EH @ ET.T, ada_h & ada_t)}
        if "clip" in pilih:
            teks["teks_foto"] = (EH @ T_clip.T, np.repeat(ada_h, len(tn), axis=1))
        for nama, (S, ada) in teks.items():
            r = nilai(np.where(ada, S, S.min()), hn, tn)
            r.update(varian=f"[{nama_sk}] {nama} saja")
            rows.append(r)
            cetak(r)
        Zt = sum(z(S, ada) for S, ada in teks.values()) / len(teks)
        for (m, latar), S in skor_foto.items():
            for w in (0.1, 0.2, 0.3, 0.4, 0.5):
                r = nilai((1 - w) * z(S) + w * Zt, hn, tn)
                r.update(varian=f"[{nama_sk}] {m} {latar} + teks w={w}")
                rows.append(r)
            terbaik = max((x for x in rows if x["varian"].startswith(f"[{nama_sk}] {m} {latar} ")),
                          key=lambda x: (x["top1"], x["top5"], -x["rata_peringkat"]))
            cetak(terbaik)

    kolom = ["varian", "top1", "top5", "rata_peringkat", "detik_per_foto", "skor_benar", "skor_salah_rata", "p95_salah", "gagal"]
    out = os.path.join(HERE, "hasil_eksperimen_v2.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=kolom, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    urut = lambda r: (-r["top1"], -r["top5"], r["rata_peringkat"])  # noqa: E731
    print("\n=== 5 VARIAN TERBAIK: FOTO SAJA ===")
    for r in sorted((r for r in rows if r["varian"].startswith("foto ")), key=urut)[:5]:
        cetak(r)
    for sk in ("mirip", "beda"):
        pilihan = [r for r in rows if r["varian"].startswith(f"[{sk}]")]
        if pilihan:
            print(f"\n=== 5 VARIAN TERBAIK: FOTO + KETERANGAN {sk.upper()} ===")
            for r in sorted(pilihan, key=urut)[:5]:
                cetak(r)
    print(f"\nTersimpan: {out}")


if __name__ == "__main__":
    main()
