import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from config import AppConfig, LLMConfig, TTSConfig
from dialogue.conversation import Conversation
from dialogue.performance import from_jev_choice
from frontend.web import WebChatService, create_app
from frontend.playback import PlaybackLedger


@pytest.mark.asyncio
async def test_kev_delivered_while_llm_and_tts_are_blocked_and_interrupt_wakes_them():
    release = asyncio.Event()
    kev_started = asyncio.Event()
    cancelled = set()

    async def tokens(_messages):
        yield '【说话语气：温柔】第一句话。'
        try:
            await release.wait()
        finally:
            cancelled.add('llm')

    async def synthesize(*args, **kwargs):
        try:
            await release.wait()
        finally:
            cancelled.add('tts')

    async def decide(history, prefix):
        assert prefix == '第一句话。'
        kev_started.set()
        return from_jev_choice('gentle', 'mild', .8, min_confidence=.4)

    llm = AsyncMock()
    llm.stream_chat = tokens
    service = WebChatService(llm, AsyncMock(synthesize=synthesize), jev_client=AsyncMock(ask_messages=decide))
    interrupt = asyncio.Event()
    stream = service.stream('你好', Conversation(), interrupt=interrupt)
    async with asyncio.timeout(2):
        async for event in stream:
            if event['type'] == 'performance' and event['source'] == 'jev':
                break
        assert kev_started.is_set()
        interrupt.set()
        rest = [event async for event in stream]
    assert rest[-1]['type'] == 'interrupted'
    assert not any(e['type'] == 'audio' for e in rest)
    assert cancelled == {'llm', 'tts'}


@pytest.mark.asyncio
async def test_slow_kev_does_not_delay_done():
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def tokens(_messages):
        yield '第一句话。'

    async def decide(*_args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def synthesize(*_args, **_kwargs):
        await started.wait()
        return b'wav'

    llm = AsyncMock()
    llm.stream_chat = tokens
    service = WebChatService(llm, AsyncMock(synthesize=synthesize), jev_client=AsyncMock(ask_messages=decide))
    async with asyncio.timeout(2):
        events = [e async for e in service.stream('hello', Conversation())]
    assert events[-1]['type'] == 'done'
    assert cancelled.is_set()


@pytest.mark.parametrize('score', [float('nan'), float('inf'), -1, 2, {}, 'bad', True, None])
def test_invalid_confidence_never_controls_stage(score):
    assert from_jev_choice('gentle', 'moderate', score, min_confidence=.4) is None


def test_ledger_trims_only_current_reply_and_ignores_duplicate_receipts():
    conversation = Conversation()
    conversation.add_user_message('问题')
    conversation.add_assistant_message('一。二。')
    ledger = PlaybackLedger('turn', sentences=['一。', '二。'], audio={0, 1}, committed_text='一。二。')
    ledger.acknowledge(0, 1, 'started')
    ledger.acknowledge(1, 0, 'started')
    ledger.cancel()
    ledger.trim(conversation)
    assert conversation.get_messages()[-1]['content'] == '一。'
    ledger.trim(conversation)
    assert conversation.get_messages()[-1]['content'] == '一。'


@pytest.mark.asyncio
async def test_v2_protocol_and_interrupt_after_done_trim_before_next_prompt():
    prompts = []

    async def tokens(messages):
        prompts.append(messages)
        yield '【动作：点头】第一句话。第二句话。'

    llm = AsyncMock()
    llm.stream_chat = tokens
    service = WebChatService(llm, AsyncMock(synthesize=AsyncMock(return_value=b'wav')))
    app = create_app(service=service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/chat', json=dict(v=2, turn_id='one', session_id='s', message='你好'))
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert all(e['v'] == 2 and e['turn_id'] == 'one' for e in events)
        sentences = [e for e in events if e['type'] == 'sentence']
        assert [e['index'] for e in sentences] == [0, 1]
        assert sentences[0]['motion'] == '点头'
        assert not any(e['type'] == 'motion' for e in events)
        assert events[-1]['sentence_count'] == 2
        invalid = await client.post('/api/playback', json=dict(session_id='s', turn_id='one', index=99, event_seq=0, kind='started'))
        assert invalid.status_code == 400
        await client.post('/api/interrupt', json=dict(session_id='s', turn_id='one', highest_started=0))
        await client.post('/api/chat', json=dict(v=2, turn_id='two', session_id='s', message='继续'))
        assert any(m['role'] == 'assistant' and m['content'].endswith('第一句话。') for m in prompts[-1])
        assert not any('第二句话。' in m['content'] for m in prompts[-1] if m['role'] == 'assistant')
        stale = await client.post('/api/interrupt', json=dict(session_id='s', turn_id='one'))
        assert stale.json()['status'] == 'stale'


def test_exact_started_indices_exclude_audio_that_failed_in_browser():
    ledger = PlaybackLedger('t', sentences=['一。', '二。'], audio={0, 1})
    ledger.cancel(highest_started=1, started_indices=[1])
    assert ledger.started == {1}
    ledger.acknowledge(0, 100, 'started')
    assert ledger.started == {1}


@pytest.mark.asyncio
async def test_playback_trim_survives_session_restart(tmp_path):
    async def tokens(_messages):
        yield '第一句话。第二句话。'

    llm = AsyncMock()
    llm.stream_chat = tokens
    service = WebChatService(llm, AsyncMock(synthesize=AsyncMock(return_value=b'wav')))
    config = AppConfig(
        llm=LLMConfig(api_key='key', base_url='https://example.test', model='model'),
        tts=TTSConfig(base_url='http://localhost:5000'),
        database_path=str(tmp_path / 'sessions.db'),
    )
    app = create_app(service=service, config=config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/chat', json=dict(v=2, turn_id='one', session_id='s', message='你好'))
        assert '"type": "done"' in response.text
        assert (await client.post('/api/playback', json=dict(session_id='s', turn_id='one', index=0, event_seq=0, kind='started'))).status_code == 200
        assert (await client.post('/api/interrupt', json=dict(session_id='s', turn_id='one', started_indices=[0]))).status_code == 200

    restarted = create_app(service=service, config=config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url='http://test') as client:
        messages = (await client.get('/api/history', params=dict(session_id='s'))).json()['messages']
    assert messages == [
        {'role': 'user', 'content': '你好'},
        {'role': 'assistant', 'content': '第一句话。'},
    ]
