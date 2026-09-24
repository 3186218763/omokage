import { EMOTIONS, MOTIONS, type ChatEvent, type HealthStatus } from "../types";

/** discriminated-union type guard：JSON.parse 返回 unknown，禁 any 下必须窄化。 */
export function isChatEvent(value: unknown): value is ChatEvent {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  const index = (n: unknown) => typeof n === "number" && Number.isSafeInteger(n) && n >= 0;
  const oneOf = <T extends readonly string[]>(set: T, value: unknown) =>
    (set as readonly string[]).includes(String(value));
  if (v.v !== 2 || typeof v.turn_id !== "string" || !v.turn_id) return false;
  switch (v.type) {
    case "sentence":
      return typeof v.text === "string" && index(v.index) && (v.motion === null || oneOf(MOTIONS, v.motion))
        && (v.pause_ms === undefined || [0, 300, 700, 1200].includes(Number(v.pause_ms)));
    case "audio":
      return typeof v.audio === "string" && index(v.index)
        && (v.mime_type === undefined || v.mime_type === "audio/wav" || v.mime_type === "audio/mpeg");
    case "audio_error":
      return typeof v.message === "string" && index(v.index);
    case "error":
    case "storage_warning":
      return typeof v.message === "string";
    case "timing":
      return true; // 诊断事件：结构宽松，前端不消费
    case "done":
      return index(v.sentence_count);
    case "interrupted":
      return true;
    case "performance":
      return oneOf(EMOTIONS, v.emotion)
        && index(v.revision)
        && typeof v.intensity === "number" && Number.isFinite(v.intensity) && v.intensity >= 0 && v.intensity <= 1
        && typeof v.confidence === "number" && Number.isFinite(v.confidence) && v.confidence >= 0 && v.confidence <= 1
        && (v.source === "speaking_style" || v.source === "jev" || v.source === "kev")
        && index(v.decay_ms);
    default:
      return false;
  }
}

export async function* streamChat(
  message: string,
  sessionId: string,
  turnId: string,
): AsyncGenerator<ChatEvent> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ v: 2, message, session_id: sessionId, turn_id: turnId }),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error || `请求失败（${response.status}）`);
  }
  const stream = response.body;
  if (!stream) throw new Error("浏览器不支持流式响应");
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() ?? "";
      for (const chunk of chunks) {
        if (!chunk.startsWith("data: ")) continue;
        const event = JSON.parse(chunk.slice(6)) as unknown;
        if (!isChatEvent(event)) throw new Error("未知事件类型");
        if (event.turn_id !== turnId) throw new Error("回复轮标识不匹配");
        if (["done", "interrupted", "error"].includes(event.type)) terminal = true;
        yield event;
      }
    }
    if (!terminal) throw new Error("回复连接提前结束");
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function transcribeAudio(blob: Blob): Promise<string> {
  const mediaType = (blob.type || "audio/webm").split(";")[0];
  const response = await fetch("/api/transcribe", {
    method: "POST",
    headers: { "Content-Type": mediaType },
    body: blob,
  });
  const result = (await response.json().catch(() => ({}))) as {
    text?: string;
    error?: string;
  };
  if (!response.ok) throw new Error(result.error || "识别失败");
  const text = result.text ?? "";
  if (!text.trim()) throw new Error("没有识别到语音");
  return text;
}

export async function resetSession(sessionId: string): Promise<void> {
  const response = await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) throw new Error("清空对话失败");
}

/** 让路：请后端停掉该会话正在说的这轮话。没人在说也无害。 */
export async function interruptSession(sessionId: string, turnId: string, highestStarted: number, startedIndices: number[]): Promise<void> {
  await fetch("/api/interrupt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, turn_id: turnId, highest_started: highestStarted, started_indices: startedIndices }),
  });
}

export async function fetchHealth(): Promise<HealthStatus> {
  const response = await fetch("/healthz");
  if (!response.ok) throw new Error("健康检查失败");
  return (await response.json()) as HealthStatus;
}

interface HistoryResponse {
  messages: { role: "user" | "assistant"; content: string }[];
}

export async function fetchHistory(sessionId: string): Promise<HistoryResponse> {
  const response = await fetch(`/api/history?session_id=${encodeURIComponent(sessionId)}`);
  if (!response.ok) throw new Error("读取历史失败");
  return response.json();
}

export async function acknowledgePlayback(sessionId: string, turnId: string, index: number, eventSeq: number, kind: "started" | "ended" | "failed"): Promise<void> {
  await fetch("/api/playback", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, turn_id: turnId, index, event_seq: eventSeq, kind }),
  });
}

export interface UserMemory {
  id: number;
  kind: string;
  value: string;
  source_text: string;
  updated_at: string;
  retrieval_count: number;
}
export interface MemoryState { enabled: boolean; memories: UserMemory[] }

export async function fetchMemories(sessionId: string): Promise<MemoryState> {
  const response = await fetch(`/api/memories?session_id=${encodeURIComponent(sessionId)}`);
  if (!response.ok) throw new Error("读取记忆失败");
  return response.json();
}

export async function setMemoriesEnabled(sessionId: string, enabled: boolean): Promise<MemoryState> {
  const response = await fetch("/api/memories", {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, enabled }),
  });
  if (!response.ok) throw new Error("更新记忆设置失败");
  return response.json() as Promise<MemoryState>;
}

export async function deleteMemory(sessionId: string, id: number): Promise<void> {
  const response = await fetch(`/api/memories/${id}?session_id=${encodeURIComponent(sessionId)}`, { method: "DELETE" });
  if (!response.ok) throw new Error("删除记忆失败");
}
