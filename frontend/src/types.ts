export type ChatEvent =
  | { type: "sentence"; text: string }
  | { type: "audio"; audio: string; index: number } // base64 WAV；index = 轮内句序（TTS 预取下音频晚于后续 sentence 到达）
  | { type: "audio_error"; message: string; index: number }
  | { type: "error"; message: string }
  | { type: "done" }
  | { type: "interrupted" }                  // 让路收尾：本轮到此为止，不是错误
  | { type: "motion"; motion: string }       // 句级动作闭集：点头/摇头/歪头
  // 每轮时延观测（诊断用，不驱动 UI；字段口径见 docs/improvements/p1-10）
  | { type: "timing"; [field: string]: unknown }
  | {
      type: "performance";
      emotion: string;
      intensity: number;
      confidence: number;
      source: "speaking_style" | "jev";
      decay_ms: number;
    };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;                             // 随 sentence 事件累积，历史记录用全文
  sentences: string[];                      // 助手按句切分；弹窗只显示正在说的那一句
  audio: { url: string; error?: string }[]; // data: URL 或合成失败标记
  error?: string;
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
