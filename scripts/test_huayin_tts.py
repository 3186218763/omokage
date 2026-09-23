#!/usr/bin/env python3
"""Synthesize one sentence through the locked Huayin SBV2 API."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dialogue.tts_client import TTSClient  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="?", default="你好，今天也要加油。")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--output", type=Path, default=Path("outputs/huayin_sbv2.wav"))
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    client = TTSClient(args.base_url)
    await client.check_available()
    audio = await client.synthesize(args.text)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(audio)
    print(f"wrote {args.output} ({len(audio)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
