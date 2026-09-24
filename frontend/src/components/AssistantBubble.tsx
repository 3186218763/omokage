import { useRef } from "react";
import type { ChatMessage } from "../types";
import styles from "./SpeechBubble.module.css";

const GREETING = "你好，今天想聊点什么？";

interface AssistantBubbleProps {
  assistant: ChatMessage | null;
  activeKey: string | null;
  pending: boolean;
  playing: boolean;
  holding: boolean;
  playbackComplete: boolean;
  startedIndex: number | null;
}

export function AssistantBubble({ assistant, activeKey, pending, playing, holding, playbackComplete, startedIndex }: AssistantBubbleProps) {
  // 说话过程中只亮正在念的那一句。这轮停下来之后，留下最后一句。
  const heard = useRef({ id: "", index: -1 });
  const assistantId = assistant?.id ?? "";
  if (heard.current.id !== assistantId) heard.current = { id: assistantId, index: -1 };
  if (startedIndex !== null) heard.current.index = startedIndex;
  const speakingThis = Boolean(assistantId && activeKey?.startsWith(`${assistantId}:`));
  const line = !playbackComplete || speakingThis || playing || holding
    ? (assistant?.sentences[heard.current.index] ?? "")
    : (assistant?.sentences.at(-1) ?? "");
  const body = line || (!playbackComplete || pending ? "…" : assistant?.error ?? "");
  const text = assistant ? body : GREETING;
  const audioFailed = assistant?.audio.some((item) => item.error) ?? false;
  const showError = Boolean(assistant?.error && line);
  // 漫画式左右交替：一句从嘴左边冒、下一句从嘴右边冒
  const sideClass = heard.current.index % 2 === 0 ? styles.sideL : styles.sideR;

  return (
    <section className={`${styles.assistant} ${sideClass}`} aria-live="polite" aria-label="这一轮对话">
      <div className={`${styles.comic} ${styles.paper} ${styles.pop}`} key={`${text}`}>
        <div className={styles.name}>花音</div>
        <p className={styles.line}>{text}</p>
        {showError && <p className={styles.note}>{assistant?.error}</p>}
        {audioFailed && <p className={styles.note}>这句声音没合成出来</p>}
      </div>
    </section>
  );
}
