import { useEffect, useRef, useState } from "react";
import { deleteMemory, fetchMemories, setMemoriesEnabled, type MemoryState } from "../api/client";
import type { ChatMessage as ChatMessageModel } from "../types";
import { ChatMessage } from "./ChatMessage";
import styles from "./HistoryPanel.module.css";

interface HistoryPanelProps {
  open: boolean;
  sessionId: string;
  messages: ChatMessageModel[];
  disabled: boolean;
  activeKey: string | null;
  isPlaying: boolean;
  waveform: number[];
  currentTime: number;
  duration: number;
  formatTime: (seconds: number) => string;
  onToggleAudio: (message: ChatMessageModel, index: number) => void;
  onReset: () => void;
  onClose: () => void;
}

export function HistoryPanel({
  open,
  sessionId,
  messages,
  disabled,
  activeKey,
  isPlaying,
  waveform,
  currentTime,
  duration,
  formatTime,
  onToggleAudio,
  onReset,
  onClose,
}: HistoryPanelProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const [memory, setMemory] = useState<MemoryState | null>(null);
  const [memoryError, setMemoryError] = useState("");

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void fetchMemories(sessionId)
      .then((state) => { if (!cancelled) { setMemory(state); setMemoryError(""); } })
      .catch(() => { if (!cancelled) setMemoryError("记忆暂时不可用"); });
    return () => { cancelled = true; };
  }, [open, sessionId]);

  const toggleMemory = async (enabled: boolean) => {
    try { setMemory(await setMemoriesEnabled(sessionId, enabled)); setMemoryError(""); }
    catch { setMemoryError("更新记忆设置失败"); }
  };
  const removeMemory = async (id: number) => {
    try {
      await deleteMemory(sessionId, id);
      setMemory(await fetchMemories(sessionId));
      setMemoryError("");
    } catch { setMemoryError("删除记忆失败"); }
  };

  useEffect(() => {
    if (open) closeRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [open, messages]);

  return (
    <>
      <div
        className={`${styles.overlay} ${open ? styles.overlayVisible : ""}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        id="history-panel"
        className={`${styles.panel} ${open ? styles.open : ""}`}
        role="complementary"
        aria-label="这一段对话记录"
        aria-hidden={!open}
        inert={!open}
      >
        <header className={styles.head}>
          <h2>这一段对话</h2>
          <button
            type="button"
            className={styles.close}
            ref={closeRef}
            onClick={onClose}
            aria-label="关闭记录"
          >
            关闭
          </button>
        </header>
        <div className={styles.list} ref={listRef}>
          {messages.length === 0 && <p className={styles.empty}>还没有对话。</p>}
          {messages.map((message) => (
            <ChatMessage
              key={message.id}
              message={message}
              activeKey={activeKey}
              isPlaying={isPlaying}
              waveform={waveform}
              currentTime={currentTime}
              duration={duration}
              formatTime={formatTime}
              onToggleAudio={onToggleAudio}
            />
          ))}
        </div>
        <footer className={styles.foot}>
          <div className={styles.memoryHead}>
            <strong>关于你的记忆</strong>
            <label className={styles.memoryToggle}>
              <input type="checkbox" checked={memory?.enabled ?? false}
                onChange={(event) => { void toggleMemory(event.target.checked); }} disabled={disabled || !memory} />
              保存
            </label>
          </div>
          {memoryError && <p className={styles.memoryError}>{memoryError}</p>}
          {memory?.enabled && (
            <div className={styles.memoryList}>
              {memory.memories.length === 0 && <span>尚无记忆</span>}
              {memory.memories.map((item) => (
                <div className={styles.memoryRow} key={item.id}>
                  <span title={item.source_text}>{item.value}</span>
                  <button type="button" onClick={() => { void removeMemory(item.id); }} aria-label={`删除记忆：${item.value}`}>删除</button>
                </div>
              ))}
            </div>
          )}
          <button type="button" className={styles.reset} onClick={onReset} disabled={disabled}>
            清空对话与记忆
          </button>
          <p className={styles.note}>AI 复刻纪念 · 非本人</p>
        </footer>
      </aside>
    </>
  );
}
