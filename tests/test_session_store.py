from dialogue.conversation import Conversation
from dialogue.session_store import SessionStore


def test_session_store_restores_messages_times_summary_and_delete(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    conversation = Conversation(recent_turns=1, summary_trigger_turns=2)
    for index in range(2):
        conversation.add_user_message(f"question {index}")
        conversation.add_assistant_message(f"answer {index}")
    plan = conversation.plan_compaction()
    assert plan is not None
    assert conversation.apply_compaction(plan, "older summary")
    expected = conversation.snapshot()

    store.save("session-1", conversation)
    restored = Conversation(recent_turns=1, summary_trigger_turns=2)
    restored.restore(SessionStore(tmp_path / "sessions.db").load("session-1"))
    assert restored.snapshot() == expected

    store.delete("session-1")
    assert store.load("session-1") is None


def test_memory_is_opt_in_recalled_and_deleted_with_session(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    assert store.remember_user_message("one", "我叫小林。") == []
    store.set_memory_enabled("one", True)
    entries = store.remember_user_message("one", "我叫小林，我喜欢冰淇淋。")
    assert {item["value"] for item in entries} == {"小林", "冰淇淋"}
    assert any("小林" in item for item in store.recall("one", "你还记得我的名字吗"))

    store.delete_memory("one", int(entries[0]["id"]))
    assert len(store.list_memories("one")) == 1
    store.set_memory_enabled("one", False)
    assert store.recall("one", "你还记得吗") == []
    store.delete("one")
    assert store.list_memories("one") == []
