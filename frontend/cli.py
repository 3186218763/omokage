"""AI 花音 CLI 命令行界面。"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from dialogue.audio_player import AudioPlayer
from dialogue.conversation import Conversation
from dialogue.llm_client import LLMClient
from dialogue.orchestrator import Orchestrator
from dialogue.tts_client import TTSClient


async def main() -> None:
    config = load_config()

    llm = LLMClient(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        temperature=config.llm.temperature,
        max_tokens=config.llm.max_tokens,
    )
    tts = TTSClient(base_url=config.tts.base_url, timeout=config.tts.timeout)
    try:
        await tts.check_available()
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return
    player = AudioPlayer()
    orchestrator = Orchestrator(
        llm,
        tts,
        player,
        max_chars=config.max_sentence_chars,
        min_chars=config.min_sentence_chars,
    )
    conversation = Conversation(
        recent_turns=config.recent_turns,
        summary_trigger_turns=config.summary_trigger_turns,
        summary_trigger_chars=config.summary_trigger_chars,
        summary_max_chars=config.summary_max_chars,
    )

    print("=" * 52)
    print("       🌸 AI 花音 — 对话模式 (Ctrl+C 退出)")
    print("=" * 52)

    while True:
        try:
            user_input = (await asyncio.to_thread(input, "\n你 > ")).strip()
            if not user_input:
                continue

            print("花音 > ", end="", flush=True)
            async for sentence in orchestrator.chat(user_input, conversation):
                print(sentence, end="", flush=True)
            print()

        except KeyboardInterrupt:
            print("\n\n再见～ 🌸")
            break
        except Exception as e:
            print(f"\n❌ 出错了：{e}")


if __name__ == "__main__":
    asyncio.run(main())
