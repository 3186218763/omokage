/** 表演情绪 → Live2D 参数。数值与 dialogue/performance.py 的 VAD 表一致。 */

import { EMOTIONS } from "../types";

export interface Vad {
  valence: number;
  arousal: number;
  dominance: number;
}

const VAD: Record<(typeof EMOTIONS)[number], Vad> = {
  日常: { valence: 0.55, arousal: 0.35, dominance: 0.5 },
  元气: { valence: 0.8, arousal: 0.75, dominance: 0.6 },
  温柔: { valence: 0.7, arousal: 0.25, dominance: 0.4 },
  俏皮: { valence: 0.75, arousal: 0.6, dominance: 0.55 },
  倔强: { valence: 0.45, arousal: 0.55, dominance: 0.75 },
  惊讶: { valence: 0.5, arousal: 0.8, dominance: 0.45 },
};

const DEFAULT_EMOTION: (typeof EMOTIONS)[number] = "日常";

export function normalizeEmotion(emotion: string): (typeof EMOTIONS)[number] {
  return EMOTIONS.find((name) => name === emotion) ?? DEFAULT_EMOTION;
}

export function performanceVad(emotion: string, intensity: number): Vad {
  const base = VAD[normalizeEmotion(emotion)];
  const gain = 0.65 + 0.35 * clamp01(intensity);
  return {
    valence: base.valence,
    arousal: clamp01(base.arousal * gain),
    dominance: base.dominance,
  };
}

export function blendParams(
  emotion: string,
  intensity: number,
  timeSec: number,
  mouth: number,
): Record<string, number> {
  const name = normalizeEmotion(emotion);
  const vad = performanceVad(name, intensity);
  const smile = (vad.valence - 0.5) * 2;
  const surprise = name === "惊讶" ? 1 : 0;
  const blinkPhase = ((timeSec % 4.3) + 4.3) % 4.3;
  const blink = blinkPhase < 0.18 ? 1 - Math.sin(Math.PI * blinkPhase / 0.18) : 1;
  const sway = Math.sin(timeSec * 0.7) * (3 + vad.arousal * 6);
  return {
    ParamMouthOpenY: clamp01(mouth),
    ParamMouthForm: clamp(smile, -1, 1),
    ParamEyeLSmile: clamp01(Math.max(0, smile) * intensity),
    ParamEyeRSmile: clamp01(Math.max(0, smile) * intensity),
    ParamEyeLOpen: clamp(0.85 - Math.max(0, smile) * 0.25 + surprise * 0.2, 0, 1.2) * blink,
    ParamEyeROpen: clamp(0.85 - Math.max(0, smile) * 0.25 + surprise * 0.2, 0, 1.2) * blink,
    ParamBrowLY: clamp((vad.dominance - 0.5) * 0.8 + surprise * 0.45, -1, 1),
    ParamBrowRY: clamp((vad.dominance - 0.5) * 0.8 + surprise * 0.45, -1, 1),
    ParamBrowLAngle: surprise * 0.3,
    ParamBrowRAngle: surprise * -0.3,
    ParamAngleX: sway,
    ParamAngleY: Math.sin(timeSec * 0.45) * 2,
    ParamAngleZ: sway * 0.2,
    ParamBodyAngleX: sway * 0.12,
    ParamBodyAngleZ: sway * 0.18,
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function clamp01(value: number): number {
  return clamp(value, 0, 1);
}
