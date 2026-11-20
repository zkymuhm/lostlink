from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

from . import matching  # noqa: E402

templates.env.globals.update(persen_mirip=matching.persen, tingkat_mirip=matching.tingkat, batas_tampil=matching.BATAS_TAMPIL)


def aset(path: str) -> str:
    """URL file statis + ?v=<waktu ubah>, supaya browser tidak memakai CSS/JS lama dari cache."""
    f = Path(__file__).parent / "static" / path
    try:
        return f"/static/{path}?v={int(f.stat().st_mtime)}"
    except OSError:
        return f"/static/{path}"


templates.env.globals["aset"] = aset


# Tujuan tombol "Kembali": ikuti halaman asal (Referer) bila jelas, selain itu pakai tujuan bawaan halaman.
_ASAL = [
    (r"^/$", "Kembali ke beranda"),
    (r"^/laporan(\?.*)?$", "Kembali ke hasil pencarian"),
    (r"^/saya$", "Kembali ke laporanku"),
    (r"^/rekomendasi(/\d+)?(\?.*)?$", "Kembali ke rekomendasi"),
    (r"^/laporan/\d+$", "Kembali ke barang"),
    (r"^/admin/\w+(\?.*)?$", "Kembali ke halaman admin"),
]


def kembali(request, bawaan_url: str, bawaan_label: str) -> tuple[str, str]:
    import re
    from urllib.parse import urlsplit

    ref = request.headers.get("referer", "")
    if ref:
        u = urlsplit(ref)
        if u.netloc == request.url.netloc:
            jalur = u.path + (f"?{u.query}" if u.query else "")
            if jalur != request.url.path:
                for pola, label in _ASAL:
                    if re.match(pola, jalur):
                        return jalur, label
    return bawaan_url, bawaan_label


templates.env.globals["kembali"] = kembali
