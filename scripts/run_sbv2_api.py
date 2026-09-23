#!/usr/bin/env python3
"""Start the locked Huayin Style-Bert-VITS2 TTS API (POST /tts)."""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SBV2_ROOT = Path("/home/mtr/tt/Style-Bert-VITS2")
DEFAULT_ASSETS_DIR = DEFAULT_SBV2_ROOT / "model_assets"
DEFAULT_MODEL_NAME = "huayin"
DEFAULT_SPEAKER_NAME = "花音"
DEFAULT_STYLE = "Neutral"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sbv2-root", type=Path, default=DEFAULT_SBV2_ROOT)
    parser.add_argument("--assets-dir", type=Path, default=None)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--speaker-name", default=DEFAULT_SPEAKER_NAME)
    parser.add_argument("--style", default=DEFAULT_STYLE)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--length", type=float, default=1.0)
    parser.add_argument("--sdp-ratio", type=float, default=0.2)
    parser.add_argument("--noise", type=float, default=0.6)
    parser.add_argument("--noisew", type=float, default=0.8)
    parser.add_argument("--style-weight", type=float, default=1.0)
    return parser.parse_args()


SERVING_PIN = "serving.txt"


def resolve_weight(model_dir: Path) -> Path:
    """Prefer ``serving.txt`` so a mid-training restart does not load a fresh checkpoint."""
    pin = model_dir / SERVING_PIN
    if pin.is_file():
        name = pin.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        pinned = model_dir / name
        if name and pinned.is_file():
            return pinned
    weights = [
        path
        for path in model_dir.iterdir()
        if path.suffix in {".safetensors", ".pth", ".pt"} and not path.name.startswith(".")
    ]
    if not weights:
        raise FileNotFoundError(f"no Style-Bert-VITS2 weights in {model_dir}")
    return max(weights, key=lambda path: path.stat().st_mtime)


def build_engine(
    sbv2_root: Path,
    assets_dir: Path,
    *,
    model_name: str,
    speaker_name: str,
    style: str,
    device: str,
    length: float,
    sdp_ratio: float,
    noise: float,
    noisew: float,
    style_weight: float,
):
    sys.path.insert(0, str(sbv2_root))
    from scipy.io import wavfile

    from style_bert_vits2.constants import Languages
    from style_bert_vits2.tts_model import TTSModel

    model_dir = assets_dir / model_name
    weight_path = resolve_weight(model_dir)
    print(f"loading weight {weight_path.name}", flush=True)
    config_path = model_dir / "config.json"
    style_path = model_dir / "style_vectors.npy"
    if not config_path.is_file():
        raise FileNotFoundError(f"missing {config_path}")
    if not style_path.is_file():
        raise FileNotFoundError(f"missing {style_path}")
    model = TTSModel(
        model_path=weight_path,
        config_path=config_path,
        style_vec_path=style_path,
        device=device,
    )
    if speaker_name not in model.spk2id:
        available = ", ".join(model.spk2id) or "(none)"
        raise SystemExit(f"speaker {speaker_name!r} not in model; have: {available}")
    if style not in model.style2id:
        available = ", ".join(model.style2id) or "(none)"
        raise SystemExit(f"style {style!r} not in model; have: {available}")
    speaker_id = model.spk2id[speaker_name]
    model.load()

    def synthesize(text: str) -> bytes:
        sample_rate, audio = model.infer(
            text=text,
            language=Languages.ZH,
            speaker_id=speaker_id,
            sdp_ratio=sdp_ratio,
            noise=noise,
            noise_w=noisew,
            length=length,
            line_split=True,
            style=style,
            style_weight=style_weight,
        )
        buffer = io.BytesIO()
        wavfile.write(buffer, sample_rate, audio)
        return buffer.getvalue()

    return synthesize


def main() -> int:
    args = parse_args()
    sbv2_root = args.sbv2_root.expanduser().resolve()
    assets_dir = (args.assets_dir or (sbv2_root / "model_assets")).expanduser().resolve()
    if not sbv2_root.is_dir():
        raise SystemExit(f"Style-Bert-VITS2 root not found: {sbv2_root}")

    sys.path.insert(0, str(PROJECT_ROOT))
    from dialogue.tts_api import create_tts_app

    synthesize = build_engine(
        sbv2_root,
        assets_dir,
        model_name=args.model_name,
        speaker_name=args.speaker_name,
        style=args.style,
        device=args.device,
        length=args.length,
        sdp_ratio=args.sdp_ratio,
        noise=args.noise,
        noisew=args.noisew,
        style_weight=args.style_weight,
    )
    app = create_tts_app(
        synthesize,
        model_name=args.model_name,
        speaker_name=args.speaker_name,
    )
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("需要 uvicorn：pip install -e '.[web]'") from exc
    print(
        f"starting Huayin SBV2 API on http://{args.host}:{args.port} "
        f"model={args.model_name} speaker={args.speaker_name}",
        flush=True,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
