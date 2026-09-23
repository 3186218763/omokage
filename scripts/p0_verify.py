"""P0 验证脚本：文字 -> LLM -> TTS -> 播放 的完整链路。"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import sounddevice as sd
import soundfile as sf
from openai import OpenAI

from config import load_config


def generate_reply(user_text: str, config) -> str:
    client = OpenAI(api_key=config.llm.api_key, base_url=config.llm.base_url)
    response = client.responses.create(
        model=config.llm.model,
        input=[
            {"role": "system", "content": "你是真白花音，一位可爱的虚拟歌手。用简短活泼的语气回复，1-2句话。"},
            {"role": "user", "content": user_text},
        ],
    )
    return response.output_text


def synthesize_speech(text: str, config) -> bytes:
    response = httpx.post(
        f"{config.tts.base_url}/tts",
        json={"text": text},
        timeout=config.tts.timeout,
    )
    response.raise_for_status()
    return response.content


def play_audio(wav_bytes: bytes) -> None:
    audio_data, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    sd.play(audio_data, sample_rate)
    sd.wait()


def run_timing_probe(user_text: str, config) -> None:
    """跑一轮真实对话管线（LLM→切句→TTS，不播放），打印每轮时延摘要。

    用法：python scripts/p0_verify.py --timing "在吗"
    口径见 docs/improvements/p1-10-turn-latency-observability.md。
    """
    import asyncio

    from dialogue.conversation import Conversation
    from frontend.web import _default_service

    async def one_turn() -> dict | None:
        service = _default_service(config)
        timing = None
        async for event in service.stream(user_text, Conversation()):
            if event.get("type") == "timing":
                timing = event
        await service.aclose()
        return timing

    timing = asyncio.run(one_turn())
    if timing is None:
        print("未收到 timing 事件（检查 conversation.timing_event 配置）")
        return
    print(
        f"首token {timing['llm_first_token_ms']}ms | "
        f"首句 {timing['first_sentence_ms']}ms | "
        f"首音 {timing['first_audio_ms']}ms | "
        f"句间gap {timing['audio_gaps_ms']}ms | "
        f"共 {timing['sentences']} 句 / 全轮 {timing['total_ms']}ms"
    )


def main() -> None:
    config = load_config()
    if len(sys.argv) >= 3 and sys.argv[1] == "--timing":
        run_timing_probe(sys.argv[2], config)
        return
    print("=" * 52)
    print("    P0 验证 — 花音 TTS 链路测试 (输入 quit 退出)")
    print("=" * 52)

    while True:
        try:
            user_input = input("\n你 > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                break

            print("花音 > (生成中...)", end="\r", flush=True)
            reply = generate_reply(user_input, config)
            print(f"花音 > {reply}")

            print("       (合成语音...)", end="\r", flush=True)
            audio = synthesize_speech(reply, config)
            play_audio(audio)
            print("       ✓ 播放完成          ")

        except KeyboardInterrupt:
            print("\n再见")
            break
        except Exception as e:
            print(f"\n❌ 错误：{e}")


if __name__ == "__main__":
    main()
