from pathlib import Path

from scripts.export_sbv2_dataset import export_dataset, parse_annotation_line


def _write_wav(path: Path) -> None:
    # Minimal PCM WAV header + one silent frame; enough for file presence checks.
    path.write_bytes(
        b"RIFF$\x00\x00\x00WAVEfmt "
        b"\x10\x00\x00\x00\x01\x00\x01\x00"
        b"\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00"
        b"data\x00\x00\x00\x00"
    )


def test_parse_annotation_line():
    wav, speaker, lang, text = parse_annotation_line(
        "audio/00009_zh.wav|花音|ZH|我就不要你这个妈妈了。"
    )
    assert wav == "audio/00009_zh.wav"
    assert speaker == "花音"
    assert lang == "ZH"
    assert text == "我就不要你这个妈妈了。"
    assert parse_annotation_line("") is None


def test_export_dataset_writes_esd_list_and_raw_wavs(tmp_path):
    source = tmp_path / "dataset_precision"
    audio = source / "audio"
    audio.mkdir(parents=True)
    _write_wav(audio / "00009_zh.wav")
    _write_wav(audio / "00015_zh.wav")
    (source / "annotation.list").write_text(
        "audio/00009_zh.wav|花音|ZH|我就不要你这个妈妈了。\n"
        "audio/00015_zh.wav|花音|ZH|所以真的日本人喜欢的。\n",
        encoding="utf-8",
    )
    output = tmp_path / "sbv2" / "huayin"

    report = export_dataset(source, output)

    assert report["n_exported"] == 2
    assert report["n_missing"] == 0
    esd = (output / "esd.list").read_text(encoding="utf-8").splitlines()
    assert esd == [
        "00009_zh.wav|花音|ZH|我就不要你这个妈妈了。",
        "00015_zh.wav|花音|ZH|所以真的日本人喜欢的。",
    ]
    assert (output / "raw" / "00009_zh.wav").is_file()
    assert (output / "raw" / "00015_zh.wav").is_file()


def test_export_dataset_skips_missing_wavs(tmp_path):
    source = tmp_path / "dataset_precision"
    audio = source / "audio"
    audio.mkdir(parents=True)
    _write_wav(audio / "keep.wav")
    (source / "annotation.list").write_text(
        "audio/keep.wav|花音|ZH|留下。\n"
        "audio/gone.wav|花音|ZH|丢掉。\n",
        encoding="utf-8",
    )

    report = export_dataset(source, tmp_path / "out")

    assert report["n_exported"] == 1
    assert report["n_missing"] == 1
    assert report["missing"] == ["audio/gone.wav"]
