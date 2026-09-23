import { useCallback, useEffect, useRef, useState } from "react";
import { useAudioQueue } from "./hooks/useAudioQueue";
import { useChat } from "./hooks/useChat";
import { useRecorder } from "./hooks/useRecorder";
import type { ChatMessage as ChatMessageModel } from "./types";
import { Live2DStage, type Live2DHandle } from "./components/Live2DStage";
import { DialoguePopup } from "./components/DialoguePopup";
import { HistoryPanel } from "./components/HistoryPanel";
import { StatusBadge } from "./components/StatusBadge";
import { ChatInput } from "./components/ChatInput";
import type { Status } from "./hooks/useChat";
import styles from "./App.module.css";

export default function App() {
  const stageRef = useRef<Live2DHandle | null>(null);
  const recordBtnRef = useRef<HTMLButtonElement | null>(null);
  const audio = useAudioQueue({
    onRms: (value) => stageRef.current?.setMouth(value),
    // 句级动作锚定在对应音频的起播瞬间，时机跟播放窗口走
    onItemStart: (item) => {
      if (item.motion) stageRef.current?.playMotion(item.motion);
    },
  });
  const onPerformance = useCallback((event: { emotion: string; intensity: number; decay_ms: number }) => {
    stageRef.current?.setPerformance({
      emotion: event.emotion,
      intensity: event.intensity,
      decayMs: event.decay_ms,
    });
  }, []);
  const chat = useChat({ enqueueAudio: audio.enqueue, onPerformance });
  const recorder = useRecorder({ enabled: chat.asrEnabled, onTranscript: chat.send });
  const [historyOpen, setHistoryOpen] = useState(false);

  // 让路：她在说也立刻停（淡出 + 后端停流），听用户说
  const interrupt = useCallback(() => {
    if (!chat.busy && !audio.isPlaying) return;
    void chat.interrupt();
    audio.fadeStop();
  }, [chat, audio]);

  const toggleRecord = useCallback(() => {
    if (!recorder.isRecording) interrupt();
    recorder.toggle();
  }, [recorder, interrupt]);

  const onStageClick = useCallback(() => {
    if (!historyOpen) interrupt();
  }, [historyOpen, interrupt]);

  const closeHistory = useCallback(() => {
    setHistoryOpen(false);
    recordBtnRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!historyOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeHistory();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeHistory, historyOpen]);

  const displayStatus: Status = recorder.error === "mic" ? "mic-error"
    : recorder.error === "insecure" ? "insecure"
    : recorder.error === "asr" ? "asr-error"
    : recorder.isTranscribing ? "transcribing"
    : recorder.isRecording ? "recording"
    : chat.status;

  const toggleAudio = useCallback((message: ChatMessageModel, index: number) => {
    const url = message.audio[index]?.url;
    if (url) audio.toggle({ key: `${message.id}:${index}`, url });
  }, [audio]);

  const reset = useCallback(() => {
    stageRef.current?.resetIdle();
    audio.clear();
    setHistoryOpen(false);
    void chat.reset();
  }, [audio, chat]);

  const lastUser = [...chat.messages].reverse().find((message) => message.role === "user") ?? null;
  const lastAssistant = [...chat.messages].reverse().find((message) => message.role === "assistant") ?? null;

  return (
    <div className={styles.stage}>
      <Live2DStage ref={stageRef} onClick={onStageClick} />
      <div className={styles.scrim} aria-hidden="true" />
      <header className={styles.chrome}>
        <button
          type="button"
          className={styles.record}
          ref={recordBtnRef}
          onClick={() => setHistoryOpen(true)}
          aria-expanded={historyOpen}
          aria-controls="history-panel"
        >
          记录
        </button>
        <StatusBadge status={displayStatus} />
      </header>
      <div className={`${styles.dock} ${historyOpen ? styles.dockHidden : ""}`} aria-hidden={historyOpen}>
        <DialoguePopup
          userText={lastUser?.text ?? null}
          assistant={lastAssistant}
          activeKey={audio.activeKey}
          pending={chat.busy}
          playing={audio.isPlaying}
        />
        <ChatInput
          busy={chat.busy}
          asrEnabled={chat.asrEnabled}
          recording={recorder.isRecording}
          onSend={chat.send}
          onToggleRecord={toggleRecord}
        />
      </div>
      <HistoryPanel
        open={historyOpen}
        messages={chat.messages}
        disabled={chat.busy}
        activeKey={audio.activeKey}
        isPlaying={audio.isPlaying}
        waveform={audio.waveform}
        currentTime={audio.currentTime}
        duration={audio.duration}
        formatTime={audio.formatTime}
        onToggleAudio={toggleAudio}
        onReset={reset}
        onClose={closeHistory}
      />
    </div>
  );
}
