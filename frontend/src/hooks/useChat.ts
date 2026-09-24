import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage, ChatEvent } from "../types";
import { acknowledgePlayback, fetchHealth, fetchHistory, interruptSession, resetSession, streamChat } from "../api/client";
import { audioKey, type QueueItem } from "./useAudioQueue";

export type Status =
  | "online"
  | "generating"
  | "recording"
  | "transcribing"
  | "needs-key"
  | "tts-down"
  | "asr-disabled"
  | "mic-error"
  | "insecure"
  | "asr-error"
  | "error";

export interface UseChatOptions {
  enqueueAudio: (item: QueueItem) => void;
  onEvent: (event: ChatEvent) => void;
  onTurn: (turnId: string) => void;
  onCancel: () => void;
}

const SESSION_KEY = "huayin-session-id";

function newId(): string {
  return crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function loadSessionId(): string {
  const existing = localStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const created = newId();
  localStorage.setItem(SESSION_KEY, created);
  return created;
}

export function useChat({ enqueueAudio, onEvent, onTurn, onCancel }: UseChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<Status>("online");
  const [asrEnabled, setAsrEnabled] = useState(true);

  const sessionIdRef = useRef(loadSessionId());
  const busyRef = useRef(false);
  const interruptRef = useRef(false);
  const turnRef = useRef<string | undefined>(undefined);
  const highestStarted = useRef(-1);
  const eventSeq = useRef(0);
  const startedIndices = useRef(new Set<number>());
  const pauses = useRef(new Map<number, number>());

  // 健康检查 → 状态徽标与录音可用性
  useEffect(() => {
    void fetchHealth()
      .then((health) => {
        if (!health.llm_configured) setStatus("needs-key");
        else if (health.tts_available === false) setStatus("tts-down");
        else if (!health.asr_available) setStatus("asr-disabled");
        else setStatus("online");
        setAsrEnabled(health.asr_available);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    let active = true;
    void fetchHistory(sessionIdRef.current).then(({ messages: history }) => {
      if (!active || busyRef.current) return;
      setMessages((current) => current.length ? current : history.map((item) => ({
        id: newId(), role: item.role, text: item.content,
        sentences: item.role === "assistant" ? [item.content] : [], audio: [],
      })));
    }).catch(() => {});
    return () => { active = false; };
  }, []);

  /** 停掉后端正在说的这轮话：取消本地播放并通知服务端（失败静默）。 */
  const stopBackendTurn = useCallback(async () => {
    const turnId = turnRef.current;
    if (!turnId) return;
    onCancel();
    await interruptSession(sessionIdRef.current, turnId, highestStarted.current, [...startedIndices.current]).catch(() => {});
  }, [onCancel]);

  const send = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message || busyRef.current) return;
      busyRef.current = true;
      interruptRef.current = false;
      setBusy(true);
      setStatus("generating");
      await stopBackendTurn();
      const seen = new Set<string>();
      const userMessage: ChatMessage = {
        id: newId(),
        role: "user",
        text: message,
        sentences: [],
        audio: [],
      };
      const assistantId = newId();
      turnRef.current = assistantId;
      highestStarted.current = -1;
      eventSeq.current = 0;
      startedIndices.current.clear();
      pauses.current.clear();
      onTurn(assistantId);
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        text: "",
        sentences: [],
        audio: [],
      };
      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      try {
        for await (const event of streamChat(message, sessionIdRef.current, assistantId)) {
          if (event.turn_id !== assistantId || interruptRef.current) continue;
          const identity = "index" in event ? `${event.type}:${event.index}` : null;
          if (identity && seen.has(identity)) continue;
          if (identity) seen.add(identity);
          onEvent(event);
          if (event.type === "sentence") {
            pauses.current.set(event.index, event.pause_ms ?? 0);
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, text: m.text + event.text, sentences: [...m.sentences, event.text] }
                  : m,
              ),
            );
          } else if (event.type === "audio") {
            const url = `data:${event.mime_type ?? "audio/wav"};base64,${event.audio}`;
            // 动作不在事件到达时触发，而是搭在对应句的音频上，起播瞬间才动
            enqueueAudio({ key: audioKey(assistantId, event.index), url, turnId: assistantId, index: event.index, pauseMs: pauses.current.get(event.index) ?? 0 });
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, audio: Object.assign([...m.audio], { [event.index]: { url } }) } : m,
              ),
            );
          } else if (event.type === "audio_error") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, audio: Object.assign([...m.audio], { [event.index]: { url: "", error: event.message } }) }
                  : m,
              ),
            );
          } else if (event.type === "timing") {
            // 每轮时延观测事件：不驱动 UI
          } else if (event.type === "storage_warning") {
            setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, warning: event.message } : m));
          } else if (event.type === "error") {
            throw new Error(event.message);
          }
        }
        setStatus("online");
      } catch (error) {
        onCancel();
        const reason = error instanceof Error ? error.message : "未知错误";
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  text: m.text ? `${m.text}\n[${reason}]` : `请求失败：${reason}`,
                  error: reason,
                }
              : m,
          ),
        );
        setStatus("error");
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [enqueueAudio, onEvent, onTurn, onCancel, stopBackendTurn],
  );

  /** 让路：请后端停掉正在说的这轮话；本轮后续音频不再入队。 */
  const interrupt = useCallback(async () => {
    if (!turnRef.current || interruptRef.current) return;
    interruptRef.current = true;
    await stopBackendTurn();
  }, [stopBackendTurn]);

  const reportPlayback = useCallback((turnId: string, index: number, kind: "started" | "ended" | "failed") => {
    if (turnId !== turnRef.current || interruptRef.current) return;
    startedIndices.current.add(index);
    highestStarted.current = Math.max(highestStarted.current, index);
    void acknowledgePlayback(sessionIdRef.current, turnId, index, eventSeq.current++, kind).catch(() => {});
  }, []);

  const reset = useCallback(async () => {
    try {
      await resetSession(sessionIdRef.current);
      turnRef.current = undefined;
      setMessages([]);
    } catch {
      setStatus("error");
    }
  }, []);

  return { messages, busy, status, asrEnabled, sessionId: sessionIdRef.current, send, interrupt, reset, reportPlayback };
}
