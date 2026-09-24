"""说话语气参考音 + 可选整链冒烟。

用法:
  # 仅 TTS：同一句台词 × 六类 ref → outputs/smoke_speaking_styles/
  python scripts/smoke_speaking_style.py

  # 真实 LLM + TTS 两轮（需 config.yaml 与 Style-Bert-VITS2 API）
  python scripts/smoke_speaking_style.py --live-llm
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import load_config
from dialogue.conversation import Conversation
from dialogue.llm_client import LLMClient
from dialogue.orchestrator import Orchestrator
from dialogue.speaking_style import SPEAKING_STYLES, SpeakingStyleRefBank
from dialogue.tts_client import TTSClient

OUT = ROOT / "outputs" / "smoke_speaking_styles"
STYLES_ORDER = ("日常", "元气", "温柔", "俏皮", "倔强", "惊讶")
DEFAULT_TEXT = "你好呀，今天也要加油哦。"


def _tts_from_config(cfg) -> TTSClient:
    return TTSClient(base_url=cfg.tts.base_url, timeout=cfg.tts.timeout)


async def smoke_refs(text: str) -> None:
    cfg = load_config()
    tts = _tts_from_config(cfg)
    await tts.check_available()
    bank = SpeakingStyleRefBank()
    OUT.mkdir(parents=True, exist_ok=True)
    lines = [f"text: {text}", ""]
    for style in STYLES_ORDER:
        assert style in SPEAKING_STYLES
        clip = bank.resolve(style)
        if clip is None or not Path(clip.audio_path).is_file():
            raise SystemExit(f"missing ref for {style}")
        # 声线已在 TTS 服务端锁定；这里只校验参考音资产齐全并走一次合成链路。
        audio = await tts.synthesize(text)
        path = OUT / f"{style}.wav"
        path.write_bytes(audio)
        line = f"{style}: {len(audio)} B -> {path.name} | ref={clip.prompt_text}"
        print(line)
        lines.append(line)
    (OUT / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


async def smoke_live_llm() -> None:
    cfg = load_config()
    llm = LLMClient(
        api_key=cfg.llm.api_key,
        base_url=cfg.llm.base_url,
        model=cfg.llm.model,
        temperature=cfg.llm.temperature,
        max_tokens=cfg.llm.max_tokens,
    )
    tts = _tts_from_config(cfg)
    await tts.check_available()
    player = AsyncMock()
    player.play_wav_bytes = AsyncMock()
    orch = Orchestrator(llm, tts, player)
    conv = Conversation()
    OUT.mkdir(parents=True, exist_ok=True)
    for user in ("谁说你小啊", "花音晚上好"):
        print(f"=== {user}")
        async for sentence in orch.chat(user, conv):
            print(f"  {sentence}")
        hist = conv.get_messages()[-1]["content"]
        if "说话语气" in hist:
            raise SystemExit("style tag leaked into history")
        print(f"  history: {hist}")
    for i, call in enumerate(player.play_wav_bytes.await_args_list):
        path = OUT / f"llm_live_{i}.wav"
        path.write_bytes(call.args[0])
        print(f"wrote {path} ({len(call.args[0])} B)")
    print("live LLM+TTS OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default=DEFAULT_TEXT, help="ref 对比用合成文本")
    parser.add_argument(
        "--live-llm",
        action="store_true",
        help="再跑两轮真实 LLM→标签→TTS",
    )
    args = parser.parse_args()
    asyncio.run(smoke_refs(args.text))
    if args.live_llm:
        asyncio.run(smoke_live_llm())


if __name__ == "__main__":
    main()
