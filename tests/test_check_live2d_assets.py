from pathlib import Path

from scripts.check_live2d_assets import assess, resolve_model_dir


def test_assess_reports_missing_core_and_model(tmp_path: Path):
    status = assess(tmp_path)

    assert status.ready is False
    assert status.model_json is None
    assert any("live2dcubismcore.min.js" in item for item in status.missing)
    assert any("model3.json" in item for item in status.missing)


def test_assess_accepts_named_model3_and_core(tmp_path: Path):
    core = tmp_path / "core" / "live2dcubismcore.min.js"
    core.parent.mkdir(parents=True)
    core.write_text("core", encoding="utf-8")
    model = tmp_path / "models" / "hiyori" / "Hiyori.model3.json"
    model.parent.mkdir(parents=True)
    model.write_text("{}", encoding="utf-8")

    status = assess(tmp_path)

    assert status.ready is True
    assert status.model_json == model
    assert status.model_url == "/live2d/models/hiyori/Hiyori.model3.json"


def test_baicai_wins_when_both_models_exist(tmp_path: Path):
    for name in ("hiyori", "baicai"):
        path = tmp_path / "models" / name / "model3.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}", encoding="utf-8")

    assert resolve_model_dir(tmp_path) == tmp_path / "models" / "baicai"


def test_configured_model_dir_must_stay_inside_root(tmp_path: Path):
    outside = tmp_path.parent / "elsewhere"
    assert resolve_model_dir(tmp_path, str(outside)) is None


def _seed_ready_root(tmp_path: Path) -> None:
    core = tmp_path / "core" / "live2dcubismcore.min.js"
    core.parent.mkdir(parents=True)
    core.write_text("core", encoding="utf-8")
    model = tmp_path / "models" / "hiyori" / "model3.json"
    model.parent.mkdir(parents=True)
    model.write_text("{}", encoding="utf-8")


def test_background_is_optional_and_does_not_block_ready(tmp_path: Path):
    _seed_ready_root(tmp_path)

    status = assess(tmp_path)

    assert status.ready is True
    assert status.background is None
    assert status.background_url is None


def test_background_prefers_day_variant_by_default(tmp_path: Path):
    _seed_ready_root(tmp_path)
    variants = tmp_path / "backgrounds"
    variants.mkdir()
    for name in ("clubroom-evening.jpg", "clubroom-day.jpg", "clubroom-night-lights-on.jpg"):
        (variants / name).write_bytes(b"jpg")

    status = assess(tmp_path)

    assert status.background == variants / "clubroom-day.jpg"
    assert status.background_url == "/live2d/backgrounds/clubroom-day.jpg"


def test_configured_background_wins_and_must_stay_inside_root(tmp_path: Path):
    _seed_ready_root(tmp_path)
    variants = tmp_path / "backgrounds"
    variants.mkdir()
    (variants / "clubroom-day.jpg").write_bytes(b"jpg")
    (variants / "clubroom-evening.jpg").write_bytes(b"jpg")

    picked = assess(tmp_path, configured_background="backgrounds/clubroom-evening.jpg")
    assert picked.background == variants / "clubroom-evening.jpg"

    outside = assess(tmp_path, configured_background="../elsewhere.jpg")
    assert outside.background is None

    missing = assess(tmp_path, configured_background="backgrounds/absent.jpg")
    assert missing.background is None
    assert missing.ready is True
