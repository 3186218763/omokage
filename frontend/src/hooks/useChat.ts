import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../types";
import { fetchHealth, interruptSession, resetSession, streamChat } from "../api/client";
import type { QueueItem } from "./useAudioQueue";

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
  onPerformance?: (event: Extract<import("../types").ChatEvent, { type: "performance" }>) => void;
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

export function useChat({ enqueueAudio, onPerformance }: UseChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<Status>("online");
  const [asrEnabled, setAsrEnabled] = useState(true);

  const sessionIdRef = useRef(loadSessionId());
  const busyRef = useRef(false);
  const interruptRef = useRef(false);
  const pendingMotionRef = useRef<string | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

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

  const send = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message || busyRef.current) return;
      busyRef.current = true;
      interruptRef.current = false;
      pendingMotionRef.current = null;
      setBusy(true);
      setStatus("generating");
      const userMessage: ChatMessage = {
        id: newId(),
        role: "user",
        text: message,
        sentences: [],
        audio: [],
      };
      const assistantId = newId();
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        text: "",
        sentences: [],
        audio: [],
      };
      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      try {
        for await (const event of streamChat(message, sessionIdRef.current)) {
          if (event.type === "sentence") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, text: m.text + event.text, sentences: [...m.sentences, event.text] }
                  : m,
              ),
            );
          } else if (event.type === "audio") {
            // 已让路的轮：迟到的音频不再入队（淡出后再自动播放就穿帮了）
            if (interruptRef.current) continue;
            const current = messagesRef.current.find((m) => m.id === assistantId);
            const index = current?.audio.length ?? 0;
            const url = `data:audio/wav;base64,${event.audio}`;
            // 动作不在事件到达时触发，而是搭在对应句的音频上，起播瞬间才动
            const motion = pendingMotionRef.current ?? undefined;
            pendingMotionRef.current = null;
            enqueueAudio({ key: `${assistantId}:${index}`, url, motion });
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, audio: [...m.audio, { url }] } : m,
              ),
            );
          } else if (event.type === "audio_error") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, audio: [...m.audio, { url: "", error: event.message }] }
                  : m,
              ),
            );
          } else if (event.type === "performance") {
            onPerformance?.(event);
          } else if (event.type === "motion") {
            // 暂存到下一块音频上；音频起播时由音频队列回调触发
            pendingMotionRef.current = event.motion;
          } else if (event.type === "error") {
            throw new Error(event.message);
          }
        }
        setStatus("online");
      } catch (error) {
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
    [enqueueAudio, onPerformance],
  );

  /** 让路：请后端停掉正在说的这轮话；本轮后续音频不再入队。 */
  const interrupt = useCallback(async () => {
    if (!busyRef.current || interruptRef.current) return;
    interruptRef.current = true;
    await interruptSession(sessionIdRef.current).catch(() => {});
  }, []);

  const reset = useCallback(async () => {
    await resetSession(sessionIdRef.current).catch(() => {});
    setMessages([]);
  }, []);

  return { messages, busy, status, asrEnabled, send, interrupt, reset };
}
