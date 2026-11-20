#!/bin/bash
# Langkah 1b: pasang rembg (penghapus latar) lalu ulangi eksperimen agar varian tanpa_latar ikut diuji.
# Jalankan SETELAH jalankan_v2.sh selesai:  bash uji_kelayakan/jalankan_tanpa_latar.sh
cd "$(dirname "$0")/.." || exit 1
source venv/bin/activate || { echo "venv tidak ditemukan"; exit 1; }
LOG=uji_kelayakan/hasil_eksperimen_v2_tanpa_latar.log
{
  echo "== $(date) =="
  echo "== Memasang rembg (numba/llvmlite versi lama: masih punya wheel siap pakai untuk Mac Intel) =="
  pip install -q "rembg[cpu]" "numba==0.60.0" "llvmlite==0.43.0" "numpy<2" torch==2.2.2 torchvision==0.17.2 \
    && echo "OK" || { echo "rembg tetap gagal dipasang"; exit 1; }
  python -c "import torch, numpy; print('torch', torch.__version__, '| numpy', numpy.__version__)"
  echo "== Eksperimen =="
  python uji_kelayakan/eksperimen_v2.py
  echo "== SELESAI $(date) =="
} 2>&1 | tee "$LOG"
