import pytest

from dialogue.tts_api import create_tts_app, parse_tts_request


def test_parse_tts_request_accepts_text_only():
    assert parse_tts_request({"text": " 你好 "}) == "你好"


def test_parse_tts_request_ignores_extra_voice_fields():
    text = parse_tts_request(
        {
            "text": "你好",
            "speaker_id": 9,
            "model_name": "other",
            "style": "Angry",
        }
    )
    assert text == "你好"


def test_parse_tts_request_rejects_empty_or_action_only():
    with pytest.raises(ValueError, match="non-empty"):
        parse_tts_request({"text": "   "})
    with pytest.raises(ValueError, match="no speakable content"):
        parse_tts_request({"text": "（轻轻点头）"})


def test_create_tts_app_synthesizes_locked_voice():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    calls: list[str] = []

    def synthesize(text: str) -> bytes:
        calls.append(text)
        return b"RIFF-fake-wav"

    client = TestClient(create_tts_app(synthesize))
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["engine"] == "style-bert-vits2"
    assert health.json()["speaker_name"] == "花音"

    response = client.post("/tts", json={"text": "你好", "speaker_id": 99})
    assert response.status_code == 200
    assert response.content == b"RIFF-fake-wav"
    assert response.headers["content-type"].startswith("audio/wav")
    assert calls == ["你好"]

    bad = client.post("/tts", json={"text": "   "})
    assert bad.status_code == 400
