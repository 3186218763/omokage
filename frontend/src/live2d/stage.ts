import {
  SoullinkRuntime,
  loadModelProfile,
  type EmotionIntent,
  type SoullinkRuntime as Runtime,
} from "@soullink-emotion/engine";
import { Live2DRenderer } from "@soullink-emotion/live2d-pixi";
import { MOTION_DURATIONS, type Live2DManifest } from "../types";
import { blendParams, normalizeEmotion, performanceVad } from "./blend";

/** 舞台可用所需的严格版 manifest：模型与核心缺一不可。 */
export type StageManifest = Required<Pick<Live2DManifest, "model_url" | "core_url">>;

export interface PerformanceInput {
  emotion: string;
  intensity: number;
  decayMs: number;
}

export interface StageController {
  setMouth(value: number): void;
  setPerformance(input: PerformanceInput): void;
  playMotion(name: string, duration?: number, currentTime?: number): void;
  setMotionTime(currentTime: number): void;
  stopMotion(): void;
  resetIdle(): void;
  destroy(): void;
}

const PROFILE_URL = "/live2d/soullink.profile.json";
const MOUTH_ID = "ParamMouthOpenY";

/** 程序化动作闭集：句级离散事件，叠加在表演情绪底色的头部参数上。 */
interface MotionCurve {
  param: string;
  amplitude: number;
  durationSec: number;
  phase: (t: number) => number; // t∈[0,1)，返回 [-1,1] 的偏移形状
}

const MOTION_CURVES: Record<string, MotionCurve> = {
  点头: { param: "ParamAngleY", amplitude: -14, durationSec: MOTION_DURATIONS.点头, phase: (t) => Math.sin(Math.PI * t) },
  摇头: { param: "ParamAngleX", amplitude: 12, durationSec: MOTION_DURATIONS.摇头, phase: (t) => Math.sin(2 * Math.PI * t) },
  歪头: { param: "ParamAngleZ", amplitude: 12, durationSec: MOTION_DURATIONS.歪头, phase: (t) => Math.sin(Math.PI * t) },
};

interface CubismDrawableList {
  renderOrders?: ArrayLike<number>;
}

interface CubismCoreModel {
  getRenderOrders?: () => ArrayLike<number>;
  drawables?: CubismDrawableList;
}

interface CubismCoreNamespace {
  Version?: { csmGetVersion?: () => number };
  Model?: {
    fromMoc: (moc: unknown) => CubismCoreModel | null;
  };
}

function cubismNamespace(): CubismCoreNamespace | undefined {
  return (window as unknown as { Live2DCubismCore?: CubismCoreNamespace }).Live2DCubismCore;
}

function coreVersion(core: CubismCoreNamespace): number | null {
  try {
    const version = core.Version?.csmGetVersion?.();
    return typeof version === "number" && version > 0 ? version : null;
  } catch {
    return null;
  }
}

/** Cubism 5 的 wasm 在脚本 onload 之后才就绪。 */
async function waitForCubismCore(core: CubismCoreNamespace): Promise<void> {
  const deadline = performance.now() + 8000;
  while (performance.now() < deadline) {
    if (coreVersion(core) !== null) return;
    await new Promise((resolve) => window.setTimeout(resolve, 20));
  }
  throw new Error("Cubism Core 初始化超时");
}

/**
 * Cubism Core 5 把绘制顺序放到 Model.getRenderOrders()。
 * pixi-live2d-display 仍读取 drawables.renderOrders，缺这个字段时第一帧绘制会抛错，画布保持空白。
 */
function patchRenderOrders(core: CubismCoreNamespace): void {
  const modelApi = core.Model;
  const original = modelApi?.fromMoc;
  if (!modelApi || !original || (original as { patched?: boolean }).patched) return;
  const patched = function (moc: unknown): CubismCoreModel | null {
    const model = original.call(modelApi, moc);
    if (
      model?.drawables &&
      model.drawables.renderOrders == null &&
      typeof model.getRenderOrders === "function"
    ) {
      const readOrders = model.getRenderOrders.bind(model);
      Object.defineProperty(model.drawables, "renderOrders", {
        configurable: true,
        get: readOrders,
      });
    }
    return model;
  };
  (patched as { patched?: boolean }).patched = true;
  modelApi.fromMoc = patched;
}

function loadCubismCore(coreUrl: string): Promise<void> {
  const existing = cubismNamespace();
  if (existing && coreVersion(existing) !== null) {
    patchRenderOrders(existing);
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    const finish = () => {
      const core = cubismNamespace();
      if (!core) {
        reject(new Error("Cubism Core 已加载，但 Live2DCubismCore 不存在"));
        return;
      }
      waitForCubismCore(core).then(() => {
        patchRenderOrders(core);
        resolve();
      }).catch(reject);
    };
    if (existing) {
      finish();
      return;
    }
    const script = document.createElement("script");
    script.src = coreUrl;
    script.async = true;
    script.onload = () => finish();
    script.onerror = () => reject(new Error("Cubism Core 加载失败"));
    document.head.appendChild(script);
  });
}

export async function mountStage(
  container: HTMLElement,
  manifest: StageManifest,
): Promise<StageController> {
  const renderer = new Live2DRenderer(container, {
    cubismLoader: () => loadCubismCore(manifest.core_url),
  });
  const parameters = await renderer.load(manifest.model_url);

  let runtime: Runtime | null = null;
  try {
    const loaded = await loadModelProfile(PROFILE_URL);
    runtime = new SoullinkRuntime({
      profile: loaded.profile,
      emotionPersonality: { targetApproachRate: 8 },
    });
    runtime.setIdleEnabled(true);
    runtime.setLipSyncEnabled(false);
  } catch {
    runtime = null;
  }

  let mouth = 0;
  let emotion = "日常";
  let intensity = 0.55;
  let baseEmotion = "日常";
  let decayTimer = 0;
  let raf = 0;
  let last = performance.now();
  let stopped = false;
  let motion: { name: string; startSec: number; duration: number; mediaTime: number | null } | null = null;
  const previousParams: Record<string, number> = {};

  /** 动作偏移：进行中返回对头部参数的加性偏移，结束自动清空。 */
  const motionOffset = (nowSec: number): Record<string, number> | null => {
    if (!motion) return null;
    const curve = MOTION_CURVES[motion.name];
    const t = Math.max(0, ((motion.mediaTime ?? nowSec) - motion.startSec) / motion.duration);
    if (t >= 1) {
      motion = null;
      return null;
    }
    return { [curve.param]: curve.amplitude * curve.phase(t) };
  };

  const pushIntent = () => {
    if (!runtime) return;
    const intent: EmotionIntent = {
      emotion: "custom",
      intensity,
      contextTags: [emotion],
      naturalVAD: performanceVad(emotion, intensity),
    };
    runtime.triggerIntent(intent, performance.now() / 1000);
  };

  if (runtime) {
    runtime.setAudioLevelAnalyzer({
      getLevel: () => mouth,
      getPeak: () => mouth,
      isAvailable: () => true,
    });
    pushIntent();
  }

  const frame = (now: number) => {
    if (stopped) return;
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    const params = runtime
      ? { ...runtime.update(now / 1000, dt).live2dParams }
      : blendParams(emotion, intensity, now / 1000, mouth);
    // Smooth only the base, then add media-clock motion and final mouth ownership.
    for (const [key, value] of Object.entries(params)) {
      const previous = previousParams[key] ?? value;
      params[key] = previous + (value - previous) * (1 - Math.exp(-dt / 0.083));
      previousParams[key] = params[key];
    }
    const offsets = motionOffset(now / 1000);
    if (offsets) {
      for (const [key, value] of Object.entries(offsets)) {
        params[key] = (params[key] ?? 0) + value;
      }
    }
    params[MOUTH_ID] = mouth;
    for (const [key, value] of Object.entries(params)) {
      const spec = parameters[key];
      if (!spec || !Number.isFinite(value)) delete params[key];
      else params[key] = Math.max(spec.min, Math.min(spec.max, value));
    }
    renderer.setParameters(params);
    raf = requestAnimationFrame(frame);
  };
  raf = requestAnimationFrame(frame);

  return {
    setMouth(value: number) {
      mouth = Math.min(1, Math.max(0, value));
    },
    setPerformance(input: PerformanceInput) {
      const next = normalizeEmotion(input.emotion);
      if (next !== "惊讶") baseEmotion = next;
      emotion = next;
      intensity = input.intensity;
      window.clearTimeout(decayTimer);
      pushIntent();
      if (input.decayMs > 0 && next === "惊讶") {
        decayTimer = window.setTimeout(() => {
          emotion = baseEmotion;
          intensity = 0.7;
          pushIntent();
        }, input.decayMs);
      }
    },
    playMotion(name: string, duration?: number, currentTime?: number) {
      // 占线直接丢弃（不排队）；闭集外的词忽略
      if (motion || !(name in MOTION_CURVES)) return;
      motion = { name, startSec: currentTime ?? performance.now() / 1000,
        duration: duration ?? MOTION_CURVES[name].durationSec, mediaTime: currentTime ?? null };
    },
    setMotionTime(currentTime: number) {
      if (motion && motion.mediaTime !== null) motion.mediaTime = currentTime;
    },
    stopMotion() { motion = null; },
    resetIdle() {
      window.clearTimeout(decayTimer);
      emotion = "日常";
      baseEmotion = "日常";
      intensity = 0.55;
      mouth = 0;
      motion = null;
      runtime?.reset(performance.now() / 1000);
      pushIntent();
    },
    destroy() {
      stopped = true;
      cancelAnimationFrame(raf);
      window.clearTimeout(decayTimer);
      renderer.destroy();
    },
  };
}
