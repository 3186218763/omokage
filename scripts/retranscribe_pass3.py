#!/usr/bin/env python3
"""Third-pass independent ASR for mid-agreement zh clips (3-way cross-check).

Decodes with a different sample (no initial prompt, temperature 0.2) than
pass1 (prompt, temp 0) and pass2 (no prompt, temp 0.6), so three-way
agreement is strong evidence the transcript matches the audio.

Only processes zh clips whose pass1<->pass2 similarity is in [0.60, 0.85)
and that are still present in the current dataset (annotation.list).

Run: /home/mtr/miniconda3/envs/gptsovits/bin/python scripts/retranscribe_pass3.py --gpus 0,1
Output: data/dataset_hq/asr_pass3_zh.json (records keyed by basename)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from retranscribe_lib import run_sharded, segment_metrics

AUDIO_DIR = PROJECT_ROOT / "data" / "dataset_hq" / "audio"
ANNOTATION = PROJECT_ROOT / "data" / "dataset_hq" / "annotation.list"
CROSSCHECK = PROJECT_ROOT / "data" / "dataset_hq" / "crosscheck_report.json"
OUT_JSON = PROJECT_ROOT / "data" / "dataset_hq" / "asr_pass3_zh.json"

MID_MIN = 0.60
MID_MAX = 0.85


def target_names() -> list[str]:
    report = json.loads(CROSSCHECK.read_text(encoding="utf-8"))
    current = {
        line.split("|", 1)[0].split("/")[-1]
        for line in ANNOTATION.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    names = [
        r["name"]
        for r in report
        if MID_MIN <= float(r.get("sim", 0.0)) < MID_MAX and r["name"] in current
    ]
    return sorted(names)


def transcribe_one(model, path: Path) -> dict:
    segments, info = model.transcribe(
        str(path),
        language="zh",
        initial_prompt=None,
        beam_size=3,
        best_of=3,
        temperature=0.2,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
    )
    materialized = list(segments)
    text = "".join(str(getattr(s, "text", "")) for s in materialized).strip()
    return {
        "path": str(path),
        "lang": "zh",
        "text": text,
        **segment_metrics(materialized),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--gpus", default="0,1")
    args = ap.parse_args()

    names = target_names()
    wavs = [AUDIO_DIR / n for n in names]
    print(f"pass3 mid-zh jobs: {len(wavs)}", flush=True)
    if not wavs:
        return 0

    cache: dict[str, dict] = {}
    if OUT_JSON.is_file():
        cache = {Path(str(x.get("path"))).name: x for x in json.loads(OUT_JSON.read_text(encoding="utf-8"))}
    jobs = [p for p in wavs if p.name not in cache]
    print(f"cached: {len(wavs) - len(jobs)}/{len(names)}", flush=True)

    def on_result(payload: dict) -> None:
        cache[Path(str(payload["path"])).name] = payload

    run_sharded(jobs, [g.strip() for g in args.gpus.split(",") if g.strip()],
                args.model, transcribe_one, on_result, progress_every=100)

    OUT_JSON.write_text(
        json.dumps(list(cache.values()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"pass3 done -> {OUT_JSON} ({len(cache)} entries)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
