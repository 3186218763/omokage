import { useRef } from "react";
import type { ChatMessage } from "../types";
import styles from "./DialoguePopup.module.css";

const GREETING = "你好，今天想聊点什么？";

interface DialoguePopupProps {
  userText: string | null;
  assistant: ChatMessage | null;
  activeKey: string | null;
  pending: boolean;
  playing: boolean;
}

export function DialoguePopup({ userText, assistant, activeKey, pending, playing }: DialoguePopupProps) {
  // 说话过程中只亮正在念的那一句。这轮停下来之后，留下最后一句。
  const heard = useRef({ id: "", index: 0 });
  const assistantId = assistant?.id ?? "";
  if (heard.current.id !== assistantId) heard.current = { id: assistantId, index: 0 };
  const clipKey = assistantId && activeKey?.startsWith(`${assistantId}:`) ? activeKey : null;
  if (clipKey) {
    const index = Number(clipKey.slice(assistantId.length + 1));
    if (Number.isInteger(index)) heard.current.index = index;
  }
  const speakingThis = clipKey !== null;
  const line = pending || speakingThis || playing
    ? (assistant?.sentences[heard.current.index] ?? "")
    : (assistant?.sentences.at(-1) ?? "");
  const greeting = !assistant && !userText;
  const body = greeting ? GREETING : line || (pending ? "…" : assistant?.error ?? "");
  const audioFailed = assistant?.audio.some((item) => item.error) ?? false;
  const showError = Boolean(assistant?.error && line);

  return (
    <section className={styles.popup} aria-live="polite" aria-label="这一轮对话">
      <div className={styles.name}>花音</div>
      {userText && (
        <p className={styles.you}>
          <span>你</span>
          {userText}
        </p>
      )}
      <p key={body} className={styles.line}>{body}</p>
      {showError && <p className={styles.note}>{assistant?.error}</p>}
      {audioFailed && <p className={styles.note}>这句声音没合成出来</p>}
    </section>
  );
}
