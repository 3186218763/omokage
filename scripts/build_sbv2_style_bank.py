#!/usr/bin/env python3
"""Attach 说话语气 style vectors to a trained Style-Bert-VITS2 Huayin model.

Neutral stays index 0 (the dataset mean written at training start). Each closed-set
speaking style is the mean wespeaker embedding of its reference clips. The acoustic
model already consumes a continuous style vector, so this does not require a retrain.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SBV2_ROOT = Path("/home/mtr/tt/Style-Bert-VITS2")
DEFAULT_REFS = PROJECT_ROOT / "model" / "refs" / "speaking_style_refs.json"
STYLE_ORDER = ("日常", "元气", "温柔", "俏皮", "倔强", "惊讶")
NEUTRAL = "Neutral"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sbv2-root", type=Path, default=DEFAULT_SBV2_ROOT)
    parser.add_argument("--model-name", default="huayin")
    parser.add_argument("--refs", type=Path, default=DEFAULT_REFS)
    parser.add_argument("--device", default="cuda")
    return parser.parse_args()


def clip_paths(block: object, root: Path) -> list[Path]:
    if not isinstance(block, dict):
        return []
    found: list[Path] = []
    for key in ("primary",):
        item = block.get(key)
        if isinstance(item, dict) and item.get("audio"):
            found.append((root / str(item["audio"])).resolve())
    for item in block.get("alternates") or []:
        if isinstance(item, dict) and item.get("audio"):
            found.append((root / str(item["audio"])).resolve())
    return found


def load_style_clips(refs_path: Path, root: Path) -> dict[str, list[Path]]:
    payload = json.loads(refs_path.read_text(encoding="utf-8"))
    styles = payload.get("styles") or {}
    clips: dict[str, list[Path]] = {}
    for name in STYLE_ORDER:
        paths = clip_paths(styles.get(name), root)
        missing = [path for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"{name} reference audio missing: {missing[0]}"
            )
        if not paths:
            raise ValueError(f"{name} has no reference clips in {refs_path}")
        clips[name] = paths
    return clips


def stack_style_matrix(
    neutral: np.ndarray,
    style_vectors: dict[str, np.ndarray],
) -> tuple[np.ndarray, dict[str, int]]:
    neutral = np.asarray(neutral, dtype=np.float32).reshape(-1)
    rows = [neutral]
    style2id = {NEUTRAL: 0}
    for name in STYLE_ORDER:
        if name not in style_vectors:
            continue
        vector = np.asarray(style_vectors[name], dtype=np.float32).reshape(-1)
        if vector.shape != neutral.shape:
            raise ValueError(
                f"{name} vector shape {vector.shape} != neutral {neutral.shape}"
            )
        if not np.isfinite(vector).all():
            raise ValueError(f"{name} style vector contains NaN or inf")
        style2id[name] = len(rows)
        rows.append(vector)
    return np.stack(rows, axis=0), style2id


def write_style_bank(
    matrix: np.ndarray,
    style2id: dict[str, int],
    *config_paths: Path,
    vectors_path: Path,
) -> None:
    vectors_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(vectors_path, matrix)
    for config_path in config_paths:
        if not config_path.is_file():
            continue
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        data = payload.setdefault("data", {})
        data["num_styles"] = int(matrix.shape[0])
        data["style2id"] = style2id
        config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _mean_embedding(paths: list[Path], embed) -> np.ndarray:
    vectors = [np.asarray(embed(str(path)), dtype=np.float32).reshape(-1) for path in paths]
    stacked = np.stack(vectors, axis=0)
    if not np.isfinite(stacked).all():
        raise ValueError(f"non-finite style embedding in {paths}")
    return stacked.mean(axis=0)


def main() -> int:
    args = parse_args()
    sbv2_root = args.sbv2_root.expanduser().resolve()
    sys.path.insert(0, str(sbv2_root))
    from style_gen import get_style_vector

    assets = sbv2_root / "model_assets" / args.model_name
    dataset = sbv2_root / "Data" / args.model_name
    neutral_path = assets / "style_vectors.npy"
    if not neutral_path.is_file():
        raise SystemExit(f"missing dataset-mean style vector: {neutral_path}")
    existing = np.load(neutral_path)
    neutral = existing[0] if existing.ndim == 2 else existing

    clips = load_style_clips(args.refs.expanduser().resolve(), PROJECT_ROOT)
    embedded = {
        name: _mean_embedding(paths, get_style_vector) for name, paths in clips.items()
    }
    matrix, style2id = stack_style_matrix(neutral, embedded)
    write_style_bank(
        matrix,
        style2id,
        assets / "config.json",
        dataset / "config.json",
        vectors_path=neutral_path,
    )
    print(
        f"wrote {neutral_path} styles={list(style2id)} shape={tuple(matrix.shape)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
