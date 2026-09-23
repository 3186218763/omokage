#!/usr/bin/env python3
"""Synthesize a fixed Huayin prompt set from one Style-Bert-VITS2 checkpoint.

Uses the sbv2 environment. Does not touch the serving pin.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROMPTS = (
    ("日常", "今天想和大家随便聊聊天。"),
    ("元气", "今天也要开开心心的呀。"),
    ("温柔", "不要勉强，好好休息哦。"),
    ("俏皮", "哼，这可是你先说的。"),
    ("倔强", "不要，我才不要认输。"),
    ("惊讶", "诶，真的吗？"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sbv2-root", type=Path, default=Path("/home/mtr/tt/Style-Bert-VITS2"))
    parser.add_argument("--model-name", default="huayin")
    parser.add_argument("--weight", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/sbv2_v2_smoke"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--style", default="Neutral")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sbv2_root = args.sbv2_root.expanduser().resolve()
    sys.path.insert(0, str(sbv2_root))
    from scipy.io import wavfile

    from style_bert_vits2.constants import Languages
    from style_bert_vits2.tts_model import TTSModel

    model_dir = sbv2_root / "model_assets" / args.model_name
    weight = args.weight.expanduser().resolve()
    model = TTSModel(
        model_path=weight,
        config_path=model_dir / "config.json",
        style_vec_path=model_dir / "style_vectors.npy",
        device=args.device,
    )
    if args.style not in model.style2id:
        available = ", ".join(model.style2id) or "(none)"
        raise SystemExit(f"style {args.style!r} not in model; have: {available}")
    model.load()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    speaker_id = model.spk2id["花音"]
    for name, text in PROMPTS:
        sample_rate, audio = model.infer(
            text=text,
            language=Languages.ZH,
            speaker_id=speaker_id,
            style=args.style,
            style_weight=1.0,
            sdp_ratio=0.2,
            noise=0.6,
            noise_w=0.8,
            length=1.0,
            line_split=True,
        )
        dest = args.out_dir / f"{name}.wav"
        wavfile.write(dest, sample_rate, audio)
        print(f"wrote {dest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
