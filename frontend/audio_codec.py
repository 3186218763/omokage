"""Optional server-side audio compaction for SSE delivery."""

from __future__ import annotations

import asyncio


async def encode_audio(
    audio: bytes, *, encoding: str = "wav", bitrate_kbps: int = 96
) -> tuple[bytes, str]:
    """Encode WAV bytes when requested, falling back to WAV if ffmpeg is absent."""
    if encoding.lower() in {"wav", "pcm"}:
        return audio, "audio/wav"
    if encoding.lower() != "mp3":
        raise ValueError("audio encoding must be wav or mp3")
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "wav",
            "-i", "pipe:0", "-ac", "1", "-b:a", f"{bitrate_kbps}k",
            "-f", "mp3", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return audio, "audio/wav"
    encoded, error = await process.communicate(audio)
    if process.returncode != 0 or not encoded:
        detail = error.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg audio encoding failed{': ' + detail if detail else ''}")
    return encoded, "audio/mpeg"
