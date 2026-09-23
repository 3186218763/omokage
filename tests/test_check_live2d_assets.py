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
