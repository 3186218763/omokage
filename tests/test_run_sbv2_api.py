import os

from scripts.run_sbv2_api import resolve_weight


def test_resolve_weight_prefers_serving_pin(tmp_path):
    older = tmp_path / "old.safetensors"
    newer = tmp_path / "new.safetensors"
    older.write_bytes(b"old")
    newer.write_bytes(b"new")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))
    (tmp_path / "serving.txt").write_text("old.safetensors\n", encoding="utf-8")
    assert resolve_weight(tmp_path) == older


def test_resolve_weight_falls_back_to_latest_mtime(tmp_path):
    older = tmp_path / "old.safetensors"
    newer = tmp_path / "new.safetensors"
    older.write_bytes(b"old")
    newer.write_bytes(b"new")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))
    assert resolve_weight(tmp_path) == newer
