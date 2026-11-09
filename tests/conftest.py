"""Lingkungan test: database dan folder foto sementara, model palsu (tanpa unduh ResNet18)."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="lostlink_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["LOSTLINK_UPLOAD_DIR"] = os.path.join(_tmp, "uploads")
os.environ["LOSTLINK_FAKE_MODEL"] = "1"
