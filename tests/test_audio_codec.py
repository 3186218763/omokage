import io
import shutil
import wave

import pytest

from frontend.audio_codec import encode_audio


@pytest.mark.asyncio
async def test_wav_passthrough():
    assert await encode_audio(b"wav") == (b"wav", "audio/wav")


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg unavailable")
async def test_mp3_encoding_emits_real_audio():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000)
    encoded, mime_type = await encode_audio(buffer.getvalue(), encoding="mp3")
    assert mime_type == "audio/mpeg"
    assert encoded.startswith(b"ID3") or encoded[:2] == b"\xff\xfb"
    assert len(encoded) < len(buffer.getvalue())
