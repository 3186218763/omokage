/** 后端闭集的镜像：dialogue/speaking_style.py、performance.py、motion.py。 */
export const EMOTIONS = ["日常", "元气", "温柔", "俏皮", "倔强", "惊讶"] as const;
export const MOTIONS = ["点头", "摇头", "歪头"] as const;
/** 程序化动作曲线时长（秒），与 live2d/stage.ts 的 MOTION_CURVES 对齐。 */
export const MOTION_DURATIONS: Record<(typeof MOTIONS)[number], number> = {
  点头: 0.8,
  摇头: 1,
  歪头: 1,
};

/** GET /api/live2d 的响应形状；model_url/core_url 缺失时舞台不可用。 */
export interface Live2DManifest {
  model_url?: string;
  core_url?: string;
  background_url?: string | null;
}

export type ChatEvent = { v: 2; turn_id: string } & (
  | { type: "sentence"; text: string; index: number; motion: (typeof MOTIONS)[number] | null; pause_ms?: number }
  | { type: "audio"; audio: string; mime_type?: "audio/wav" | "audio/mpeg"; index: number } // base64；index = 轮内句序
  | { type: "audio_error"; message: string; index: number }
  | { type: "error"; message: string }
  | { type: "storage_warning"; message: string }
  | { type: "done"; sentence_count: number }
  | { type: "interrupted" }                  // 让路收尾：本轮到此为止，不是错误
  // 每轮时延观测（诊断用，不驱动 UI；字段口径见 docs/improvements/p1-10）
  | { type: "timing" }
  | {
      type: "performance";
      emotion: string;
      intensity: number;
      confidence: number;
      source: "speaking_style" | "jev" | "kev";
      revision: number;
      decay_ms: number;
    });

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;                             // 随 sentence 事件累积，历史记录用全文
  sentences: string[];                      // 助手按句切分；弹窗只显示正在说的那一句
  audio: { url: string; error?: string }[]; // data: URL 或合成失败标记
  error?: string;
  warning?: string;
}

export interface HealthStatus {
  status: string;
  service: string;
  llm_configured: boolean;
  tts_configured: boolean;
  tts_available: boolean | null;
  asr_configured: boolean;
  asr_available: boolean;
  live2d_ready?: boolean;
  jev_configured?: boolean;
}
