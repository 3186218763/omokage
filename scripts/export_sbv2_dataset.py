#!/usr/bin/env python3
"""Export dataset_precision into Style-Bert-VITS2 layout.

GPT-SoVITS annotation.list uses:
    audio/00009_zh.wav|花音|ZH|我就不要你这个妈妈了。

Style-Bert-VITS2 esd.list uses the same four fields, but wavs live under
``raw/`` and the path column is a filename (preprocess --correct_path later
rewrites it to ``wavs/<name>``).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "data" / "dataset_precision"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "sbv2" / "huayin"
DEFAULT_SPEAKER = "花音"


def parse_annotation_line(line: str) -> tuple[str, str, str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    parts = text.split("|", 3)
    if len(parts) != 4:
        raise ValueError(f"invalid annotation line: {text}")
    wav_field, speaker, language, transcript = (part.strip() for part in parts)
    if not wav_field or not transcript:
        raise ValueError(f"missing wav or text: {text}")
    return wav_field, speaker, language, transcript


def wav_name(wav_field: str) -> str:
    return Path(wav_field.replace("\\", "/")).name


def resolve_source_wav(source_dir: Path, wav_field: str) -> Path:
    name = wav_name(wav_field)
    candidates = [
        source_dir / wav_field,
        source_dir / "audio" / name,
        source_dir / name,
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(f"wav not found for {wav_field}")


def link_or_copy(src: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        os.link(src, dest)
        return "hardlink"
    except OSError:
        shutil.copy2(src, dest)
        return "copy"


def export_dataset(
    source_dir: Path,
    output_dir: Path,
    *,
    speaker: str = DEFAULT_SPEAKER,
    list_path: Path | None = None,
) -> dict:
    source_dir = source_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    annotation = list_path or (source_dir / "annotation.list")
    if not annotation.is_file():
        raise FileNotFoundError(f"annotation list not found: {annotation}")

    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    missing: list[str] = []
    copied = 0
    linked = 0
    speakers: set[str] = set()
    languages: set[str] = set()

    for raw_line in annotation.read_text(encoding="utf-8").splitlines():
        parsed = parse_annotation_line(raw_line)
        if parsed is None:
            continue
        wav_field, _listed_speaker, language, transcript = parsed
        language = language.upper()
        try:
            src = resolve_source_wav(source_dir, wav_field)
        except FileNotFoundError:
            missing.append(wav_field)
            continue
        name = wav_name(wav_field)
        method = link_or_copy(src, raw_dir / name)
        if method == "hardlink":
            linked += 1
        else:
            copied += 1
        speakers.add(speaker)
        languages.add(language)
        lines.append(f"{name}|{speaker}|{language}|{transcript}")

    if not lines:
        raise RuntimeError("no clips exported; check annotation.list and audio/")

    esd_path = output_dir / "esd.list"
    esd_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "annotation": str(annotation),
        "n_exported": len(lines),
        "n_missing": len(missing),
        "n_hardlink": linked,
        "n_copy": copied,
        "speaker": speaker,
        "speakers": sorted(speakers),
        "languages": sorted(languages),
        "missing": missing,
    }
    (output_dir / "export_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--list-path", type=Path, default=None)
    parser.add_argument("--speaker", default=DEFAULT_SPEAKER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = export_dataset(
        args.source_dir,
        args.output_dir,
        speaker=args.speaker,
        list_path=args.list_path,
    )
    print(
        f"exported {report['n_exported']} clips -> {report['output_dir']} "
        f"(hardlink={report['n_hardlink']} copy={report['n_copy']} "
        f"missing={report['n_missing']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
