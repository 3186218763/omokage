import { useEffect, useRef } from "react";
import type { ChatMessage as ChatMessageModel } from "../types";
import { ChatMessage } from "./ChatMessage";
import styles from "./HistoryPanel.module.css";

interface HistoryPanelProps {
  open: boolean;
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
          <button type="button" className={styles.reset} onClick={onReset} disabled={disabled}>
            清空这一段
          </button>
          <p className={styles.note}>AI 复刻纪念 · 非本人</p>
        </footer>
      </aside>
    </>
  );
}
