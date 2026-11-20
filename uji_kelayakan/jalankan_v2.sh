#!/bin/bash
# Langkah 1 eksperimen v2: pasang paket lalu uji model foto (EfficientNet-B0, DINOv2, CLIP; dengan/tanpa latar).
# Jalankan dari folder proyek:  bash uji_kelayakan/jalankan_v2.sh
cd "$(dirname "$0")/.." || exit 1
source venv/bin/activate || { echo "venv tidak ditemukan"; exit 1; }
LOG=uji_kelayakan/hasil_eksperimen_v2.log
{
  echo "== $(date) =="
  echo "== 1/3 Memasang sentence-transformers (versi dikunci agar torch & numpy tidak berubah) =="
  pip install -q "sentence-transformers==3.3.1" "transformers==4.46.3" "numpy<2" torch==2.2.2 torchvision==0.17.2 \
    && echo "OK" || echo "GAGAL memasang sentence-transformers"
  echo "== 2/3 Memasang rembg (opsional) =="
  # numba/llvmlite versi lama: masih punya wheel siap pakai untuk Mac Intel (versi baru minta kompilasi LLVM)
  pip install -q "rembg[cpu]" "numba==0.60.0" "llvmlite==0.43.0" "numpy<2" torch==2.2.2 torchvision==0.17.2 && echo "OK" || echo "rembg gagal dipasang: varian tanpa_latar dilewati"
  python -c "import torch, numpy; print('torch', torch.__version__, '| numpy', numpy.__version__)"
  echo "== 3/3 Eksperimen =="
  python uji_kelayakan/eksperimen_v2.py
  echo "== SELESAI $(date) =="
} 2>&1 | tee "$LOG"
