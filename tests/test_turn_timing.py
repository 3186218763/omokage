import json
import logging

from frontend.turn_timing import TurnTiming


def test_marks_record_first_occurrence_only():
    timing = TurnTiming()

    timing.mark("llm_first_token")
    timing.mark("llm_first_token")

    assert len(timing.marks) == 1


def test_marks_and_audio_sent_are_monotonic():
    timing = TurnTiming()
    timing.mark("llm_first_token")
    timing.mark_audio()
    timing.mark("jev_done")

    ordered = [timing.marks["llm_first_token"], *timing.audio_sent, timing.marks["jev_done"]]
    assert ordered == sorted(ordered)
    assert all(value >= 0 for value in ordered)


def test_as_dict_reports_ms_gaps_and_absent_marks_as_null():
    timing = TurnTiming()
    timing.mark("llm_first_token")
    timing.mark("first_sentence")
    timing.sentences = 2
    timing.audio_sent = [0.1, 0.35]
    timing.interrupted = False

    payload = timing.as_dict()

    assert payload["type"] == "timing"
    assert payload["llm_first_token_ms"] >= 0
    assert payload["first_audio_ms"] == 100
    assert payload["audio_sent_ms"] == [100, 350]
    assert payload["audio_gaps_ms"] == [250]
    assert payload["jev_dispatch_ms"] is None
    assert payload["jev_done_ms"] is None
    assert payload["sentences"] == 2
    assert payload["interrupted"] is False
    # total_ms 是真实墙钟（此刻≈0），不随手动塞入的 audio_sent 抬高
    assert payload["total_ms"] >= 0


def test_no_audio_yields_null_first_audio_and_empty_gaps():
    payload = TurnTiming().as_dict()

    assert payload["first_audio_ms"] is None
    assert payload["audio_sent_ms"] == []
    assert payload["audio_gaps_ms"] == []


def test_log_emits_one_json_line_with_type_timing(caplog):
    timing = TurnTiming()
    timing.mark("llm_first_token")

    with caplog.at_level(logging.INFO, logger="omokage.timing"):
        timing.log()

    record = caplog.records[-1]
    payload = json.loads(record.message)
    assert payload["type"] == "timing"
    assert payload["llm_first_token_ms"] >= 0
