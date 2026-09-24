import { useCallback, useEffect, useRef, useState } from "react";
import { useAudioQueue } from "./hooks/useAudioQueue";
import { useChat } from "./hooks/useChat";
import { useRecorder } from "./hooks/useRecorder";
import type { ChatMessage as ChatMessageModel } from "./types";
import { Live2DStage, type Live2DHandle } from "./components/Live2DStage";
import { AssistantBubble } from "./components/AssistantBubble";
import { UserBubble } from "./components/UserBubble";
import { HistoryPanel } from "./components/HistoryPanel";
import { StatusBadge } from "./components/StatusBadge";
import { ChatInput } from "./components/ChatInput";
import type { Status } from "./hooks/useChat";
import { PlaybackDirector, type Effect, type PlaybackEvent } from "./playback/director";
import type { ChatEvent } from "./types";
import { recordPlayback } from "./playback/telemetry";
import styles from "./App.module.css";

export default function App() {
  const stageRef = useRef<Live2DHandle | null>(null);
  const recordBtnRef = useRef<HTMLButtonElement | null>(null);
  const director = useRef(new PlaybackDirector());
  const [playbackComplete, setPlaybackComplete] = useState(true);
  const [startedIndex, setStartedIndex] = useState<number | null>(null);
  const report = useRef<(turnId: string, index: number, kind: "started" | "ended") => void>(() => {});
  const execute = useCallback((effects: Effect[]) => {
    for (const effect of effects) {
      const stage = stageRef.current;
      if (effect.type === "idle") stage?.resetIdle();
      else if (effect.type === "stopMotion") stage?.stopMotion();
      else if (effect.type === "clock") stage?.setMotionTime(effect.currentTime);
      else if (effect.type === "motion") {
        stage?.playMotion(effect.name, effect.duration, effect.currentTime);
        recordPlayback(director.current.turnId, "motion_start", effect.index);
      } else if (effect.type === "performance") {
        stage?.setPerformance({ emotion: effect.value.emotion, intensity: effect.value.intensity, decayMs: 0 });
        recordPlayback(director.current.turnId, "performance_applied");
      }
    }
  }, []);
  const onPlayback = useCallback((event: PlaybackEvent) => {
    if (event.type !== "clock") recordPlayback(event.turnId, event.type, event.index);
    if (event.type === "playing" && event.turnId === director.current.turnId && !director.current.closed) {
      setStartedIndex(event.index);
    }
    execute(director.current.dispatch(event));
    if (event.type === "ended" || event.type === "failed") {
      setPlaybackComplete(director.current.closed);
    }
    if (event.type === "playing" || event.type === "ended") {
      report.current(event.turnId, event.index, event.type === "playing" ? "started" : "ended");
    }
  }, [execute]);
  const audio = useAudioQueue({
    onRms: (value) => stageRef.current?.setMouth(value), onPlayback,
  });
  const onEvent = useCallback((event: ChatEvent) => {
    recordPlayback(event.turn_id, `received_${event.type}`, "index" in event ? event.index : undefined);
    execute(director.current.dispatch(event));
    if (event.type === "done" || event.type === "interrupted" || event.type === "error" || event.type === "audio_error") {
      setPlaybackComplete(director.current.closed);
    }
  }, [execute]);
  const onTurn = useCallback((turnId: string) => {
    audio.clear();
    setStartedIndex(null);
    setPlaybackComplete(false);
    execute(director.current.start(turnId));
    recordPlayback(turnId, "send");
  }, [audio.clear, execute]);
  const onCancel = useCallback(() => {
    recordPlayback(director.current.turnId, "interrupt");
    execute(director.current.cancel());
    setPlaybackComplete(true);
    audio.fadeStop();
  }, [execute, audio.fadeStop]);
  const chat = useChat({ enqueueAudio: audio.enqueue, onEvent, onTurn, onCancel });
  report.current = chat.reportPlayback;
  const recorder = useRecorder({ enabled: chat.asrEnabled, onTranscript: chat.send });
  const [historyOpen, setHistoryOpen] = useState(false);

  // 让路：她在说也立刻停（淡出 + 后端停流），听用户说
  const interrupt = useCallback(() => {
    if (!chat.busy && !audio.activeKey) return;
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
    if (url) {
      if (audio.activeKey !== `${message.id}:${index}`) void chat.interrupt();
      audio.toggle({ key: `${message.id}:${index}`, url });
    }
  }, [audio, chat]);

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
      <div className={`${styles.speech} ${historyOpen ? styles.speechHidden : ""}`} aria-hidden={historyOpen}>
        <AssistantBubble
          assistant={lastAssistant}
          activeKey={audio.activeKey}
          pending={chat.busy}
          playing={audio.isPlaying}
          holding={audio.holding}
          playbackComplete={playbackComplete}
          startedIndex={startedIndex}
        />
      </div>
      <div className={`${styles.dock} ${historyOpen ? styles.dockHidden : ""}`} aria-hidden={historyOpen}>
        {lastUser && <UserBubble text={lastUser.text} />}
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
        sessionId={chat.sessionId}
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
