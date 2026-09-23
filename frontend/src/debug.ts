// 表演层调试页逻辑。左栏走 App 真实路径（mountStage），右栏直连渲染器播
// Hiyori 原生动作组。一次性验证工具，不进构建产物（仅 vite dev 使用）。
import { mountStage, type StageController } from "./live2d/stage";
import { Live2DRenderer } from "@soullink-emotion/live2d-pixi";
import { blendParams } from "./live2d/blend";

interface Manifest {
  model_url?: string;
  core_url?: string;
  background_url?: string | null;
}

const EMOTIONS = ["日常", "元气", "温柔", "俏皮", "倔强", "惊讶"] as const;
const INTENSITIES: Array<[string, number]> = [
  ["mild 0.6", 0.6],
  ["moderate 0.9", 0.9],
  ["strong 1.0", 1.0],
];
const MOTIONS = ["点头", "摇头", "歪头"] as const;

// Hiyori model3.json 的动作组。Idle 组 index 0-8 → m01,m02,m03,m05..m10；TapBody → m04。
const NATIVE_MOTIONS: Array<{ group: string; index: number; label: string; duration: number }> = [
  { group: "Idle", index: 0, label: "m01", duration: 4.7 },
  { group: "Idle", index: 1, label: "m02", duration: 5.93 },
  { group: "Idle", index: 2, label: "m03", duration: 4.2 },
  { group: "TapBody", index: 0, label: "m04", duration: 4.43 },
  { group: "Idle", index: 3, label: "m05", duration: 8.57 },
  { group: "Idle", index: 4, label: "m06", duration: 5.37 },
  { group: "Idle", index: 5, label: "m07", duration: 1.9 },
  { group: "Idle", index: 6, label: "m08", duration: 2.1 },
  { group: "Idle", index: 7, label: "m09", duration: 1.6 },
  { group: "Idle", index: 8, label: "m10", duration: 4.17 },
];

// blendParams 会写的全部参数 id：原生动作播放期间全部抑制，让 motion3.json 的曲线露出来。
const WRITTEN_IDS = [
  "ParamMouthOpenY", "ParamMouthForm", "ParamEyeLSmile", "ParamEyeRSmile",
  "ParamEyeLOpen", "ParamEyeROpen", "ParamBrowLY", "ParamBrowRY",
  "ParamBrowLAngle", "ParamBrowRAngle", "ParamAngleX", "ParamAngleY",
  "ParamAngleZ", "ParamBodyAngleX", "ParamBodyAngleZ",
];

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  return node;
}

function row(label: string): HTMLDivElement {
  const div = el("div", "");
  div.className = "row";
  const lab = el("span", label);
  lab.className = "label";
  div.append(lab);
  return div;
}

async function main() {
  const response = await fetch("/api/live2d");
  if (!response.ok) throw new Error(`/api/live2d ${response.status}`);
  const manifest = (await response.json()) as Manifest;
  if (!manifest.model_url || !manifest.core_url) throw new Error("Live2D 资产未就绪");
  for (const host of [
    document.getElementById("stage-app"),
    document.getElementById("stage-native"),
    document.getElementById("stage-proto"),
  ]) {
    if (host && manifest.background_url) {
      (host as HTMLElement).style.background = `#1a2024 url("${manifest.background_url}") center/cover`;
    }
  }

  // 串行挂载：无头环境下两个舞台并发 load 会触发资源竞态（先挂的画布空白）。
  await buildAppPanel(manifest);
  buildNativePanel(manifest);
  buildProtoPanel(manifest);
}

function buildAppPanel(manifest: Manifest): Promise<void> {
  const host = document.getElementById("stage-app") as HTMLElement;
  const controls = document.getElementById("controls-app") as HTMLElement;
  const status = document.getElementById("status-app") as HTMLElement;
  let controller: StageController | null = null;
  let emotion: string = "日常";
  let intensity = 0.9;

  const say = (line: string) => { status.textContent = line; };
  const flash = (line: string) => {
    say(line);
    status.className = "status";
  };

  const emotionRow = row("情绪");
  const intensityRow = row("强度");
  const motionRow = row("动作");
  for (const name of EMOTIONS) {
    const btn = el("button", name);
    if (name === emotion) btn.classList.add("active");
    btn.onclick = () => {
      emotion = name;
      emotionRow.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
      controller?.setPerformance({
        emotion,
        intensity,
        decayMs: emotion === "惊讶" ? 1200 : 0,
      });
      flash(`setPerformance: ${emotion} × ${intensity}${emotion === "惊讶" ? "（1200ms 后衰减回落）" : ""}`);
    };
    emotionRow.append(btn);
  }
  for (const [label, value] of INTENSITIES) {
    const btn = el("button", label);
    if (value === intensity) btn.classList.add("active");
    btn.onclick = () => {
      intensity = value;
      intensityRow.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
      controller?.setPerformance({ emotion, intensity, decayMs: emotion === "惊讶" ? 1200 : 0 });
      flash(`setPerformance: ${emotion} × ${intensity}`);
    };
    intensityRow.append(btn);
  }
  for (const name of MOTIONS) {
    const btn = el("button", name);
    btn.onclick = () => {
      controller?.playMotion(name);
      flash(`playMotion: ${name}（0.8–1.0s 程序化曲线，占线时丢弃）`);
    };
    motionRow.append(btn);
  }
  const mouthRow = row("口型");
  const mouth = el("input") as HTMLInputElement;
  mouth.type = "range";
  mouth.min = "0";
  mouth.max = "1";
  mouth.step = "0.05";
  mouth.oninput = () => controller?.setMouth(Number(mouth.value));
  mouthRow.append(mouth);
  const resetBtn = el("button", "resetIdle");
  resetBtn.onclick = () => {
    controller?.resetIdle();
    emotion = "日常";
    intensity = 0.9;
    mouth.value = "0";
    emotionRow.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.textContent === "日常"));
    flash("resetIdle → 日常 × 0.55");
  };
  mouthRow.append(resetBtn);
  controls.append(emotionRow, intensityRow, motionRow, mouthRow);
  say("加载模型…");

  // 无头/vite-dev 首次加载时 mountStage 可能渲染空画布（模块首次编译时序），
  // 卸载后重挂一次即恢复；等待要够长（首次编译在后台还会跑一会儿）。
  const mountTwice = async (): Promise<StageController> => {
    const first = await mountStage(host, { model_url: manifest.model_url!, core_url: manifest.core_url! });
    await new Promise((resolve) => window.setTimeout(resolve, 2000));
    first.destroy();
    host.replaceChildren();
    return mountStage(host, { model_url: manifest.model_url!, core_url: manifest.core_url! });
  };

  return mountTwice()
    .then((stage) => {
      controller = stage;
      (window as unknown as { __stage?: unknown }).__stage = stage;
      say("模型就绪。点左侧按钮测试（App 同款代码路径，含 SoullinkRuntime）。");
    })
    .catch((error) => {
      status.className = "status err";
      say(`挂载失败：${String(error)}`);
    });
}

function buildNativePanel(manifest: Manifest) {
  const host = document.getElementById("stage-native") as HTMLElement;
  const controls = document.getElementById("controls-native") as HTMLElement;
  const status = document.getElementById("status-native") as HTMLElement;
  const say = (line: string) => { status.textContent = line; };
  say("加载模型…");

  const idleRow = row("Idle 组");
  const tapRow = row("TapBody");
  const renderer = new Live2DRenderer(host, {
    // 左栏 mountStage 已注入并 patch 过 Cubism Core；兜底再补一次脚本注入。
    cubismLoader: () => ensureCore(manifest.core_url!),
  });

  let token = 1;
  let releaseTimer = 0;
  const play = (entry: (typeof NATIVE_MOTIONS)[number]) => {
    window.clearTimeout(releaseTimer);
    renderer.applyNativeAnimation({
      token: token++,
      expression: null,
      motion: { group: entry.group, index: entry.index, priority: "force" },
      suppressParamIds: WRITTEN_IDS,
    });
    say(`播放 ${entry.group}[${entry.index}] ${entry.label}（${entry.duration}s，结束后自动解除参数抑制）`);
    releaseTimer = window.setTimeout(() => {
      renderer.applyNativeAnimation(null);
      say(`${entry.label} 结束，回到程序化底色。`);
    }, entry.duration * 1000 + 300);
  };

  void renderer
    .load(manifest.model_url!)
    .then(() => {
      for (const entry of NATIVE_MOTIONS) {
        const btn = el("button", entry.label);
        btn.onclick = () => play(entry);
        (entry.group === "TapBody" ? tapRow : idleRow).append(btn);
      }
      controls.append(idleRow, tapRow);
      say("模型就绪。m01–m03、m05–m10 属 Idle 组，m04 属 TapBody 组。");
    })
    .catch((error) => {
      status.className = "status err";
      say(`挂载失败：${String(error)}`);
    });

  let raf = 0;
  let last = performance.now();
  const frame = (now: number) => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    renderer.setParameters(blendParams("日常", 0.55, now / 1000, 0));
    void dt;
    raf = requestAnimationFrame(frame);
  };
  raf = requestAnimationFrame(frame);
  window.addEventListener("pagehide", () => {
    cancelAnimationFrame(raf);
    renderer.destroy();
  });
}

let corePromise: Promise<void> | null = null;

// ═══════════════════════════════════════════════════════════════
// ③ 原型：说话窗口对齐的动作。研究「动作应在说话期间持续、点头要多次」。
// 曲线模型独立于 stage.ts（那里是现状），方便对照调参。
// ═══════════════════════════════════════════════════════════════

interface ProtoCurve {
  durationSec: number;
  describe: string;
  offsetAt(elapsed: number): Record<string, number> | null; // null = 已结束
}

const clampNumber = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** 现状曲线：stage.ts MOTION_CURVES 的等价复刻。 */
function currentCurve(name: string): ProtoCurve {
  const table: Record<string, { param: string; amplitude: number; durationSec: number; phase: (t: number) => number }> = {
    点头: { param: "ParamAngleY", amplitude: -14, durationSec: 0.8, phase: (t) => Math.sin(Math.PI * t) },
    摇头: { param: "ParamAngleX", amplitude: 12, durationSec: 1.0, phase: (t) => Math.sin(2 * Math.PI * t) },
    歪头: { param: "ParamAngleZ", amplitude: 12, durationSec: 1.0, phase: (t) => Math.sin(Math.PI * t) },
  };
  const c = table[name];
  return {
    durationSec: c.durationSec,
    describe: `现状：单次 ${c.durationSec}s`,
    offsetAt(elapsed) {
      const t = elapsed / c.durationSec;
      if (t >= 1) return null;
      return { [c.param]: c.amplitude * c.phase(t) };
    },
  };
}

/** 提案·重复型（点头/摇头）：按音频时长定次数，振幅逐次衰减。 */
function repeatedCurve(name: string, durationMs: number): ProtoCurve {
  const spec = name === "点头"
    ? { param: "ParamAngleY", amplitude: -14, cycleSec: 0.58, perCycleBudget: 0.9, maxCycles: 4, lobes: 1 }
    : { param: "ParamAngleX", amplitude: 12, cycleSec: 0.65, perCycleBudget: 1.1, maxCycles: 3, lobes: 2 };
  const count = clampNumber(Math.floor(durationMs / 1000 / spec.perCycleBudget), 1, spec.maxCycles);
  const durationSec = count * spec.cycleSec;
  return {
    durationSec,
    describe: `提案：${count} 次 × ${spec.cycleSec}s（音频 ${(durationMs / 1000).toFixed(2)}s）`,
    offsetAt(elapsed) {
      const t = elapsed / durationSec;
      if (t >= 1) return null;
      const cycleIndex = Math.min(count - 1, Math.floor(elapsed / spec.cycleSec));
      const local = (elapsed - cycleIndex * spec.cycleSec) / spec.cycleSec;
      const amp = spec.amplitude * Math.pow(0.86, cycleIndex);
      const shape = spec.lobes === 1 ? Math.sin(Math.PI * local) : Math.sin(2 * Math.PI * local);
      return { [spec.param]: amp * shape };
    },
  };
}

/** 提案·保持型（歪头）：倾入 → 保持（微摆）→ 句末释放。 */
function holdCurve(_name: string, durationMs: number): ProtoCurve {
  const param = "ParamAngleZ";
  const amplitude = 12;
  const inSec = 0.25;
  const holdSec = Math.min((durationMs / 1000) * 0.85, 2.5);
  const outSec = 0.3;
  const durationSec = inSec + holdSec + outSec;
  const ease = (u: number) => 1 - Math.pow(1 - u, 3);
  return {
    durationSec,
    describe: `提案：倾入 ${inSec}s → 保持 ${holdSec.toFixed(2)}s → 释放 ${outSec}s`,
    offsetAt(elapsed) {
      if (elapsed >= durationSec) return null;
      let scale: number;
      if (elapsed < inSec) scale = ease(elapsed / inSec);
      else if (elapsed < inSec + holdSec) scale = 1 + Math.sin(elapsed * 2.2) * 0.08;
      else scale = 1 - ease((elapsed - inSec - holdSec) / outSec);
      return { [param]: amplitude * scale };
    },
  };
}

/** WAV 字节 → 毫秒时长（RIFF 遍历 fmt/data chunk）。生产落地时放 useChat。 */
function wavDurationMs(buf: Uint8Array): number {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  let pos = 12;
  let byteRate = 0;
  let dataSize = 0;
  while (pos + 8 <= buf.length) {
    const id = String.fromCharCode(buf[pos], buf[pos + 1], buf[pos + 2], buf[pos + 3]);
    const size = dv.getUint32(pos + 4, true);
    if (id === "fmt ") byteRate = dv.getUint32(pos + 16, true);
    if (id === "data") { dataSize = size; break; }
    pos += 8 + size + (size % 2);
  }
  return byteRate > 0 ? Math.round((dataSize / byteRate) * 1000) : 0;
}

const SENTENCES: Array<{ label: string; text: string }> = [
  { label: "短句「当然开心呀！」", text: "当然开心呀！" },
  { label: "中句「对呀对呀，你说得太对了！」", text: "对呀对呀，你说得太对了！" },
  { label: "长句「嗯，我觉得还可以吧，不过你说的也有道理。」", text: "嗯，我觉得还可以吧，不过你说的也有道理。" },
];

function buildProtoPanel(manifest: Manifest) {
  const host = document.getElementById("stage-proto") as HTMLElement;
  const controls = document.getElementById("controls-proto") as HTMLElement;
  const status = document.getElementById("status-proto") as HTMLElement;
  const say = (line: string) => { status.textContent = line; };
  say("加载模型…");

  const renderer = new Live2DRenderer(host, {
    cubismLoader: () => ensureCore(manifest.core_url!),
  });

  // 音频图：Audio 元素 → analyser → destination；RMS 驱动口型（同 useAudioQueue 思路）
  const audioEl = new Audio();
  const actx = new AudioContext();
  const analyser = actx.createAnalyser();
  analyser.fftSize = 64;
  actx.createMediaElementSource(audioEl).connect(analyser);
  analyser.connect(actx.destination);
  let smoothMouth = 0;
  const readMouth = (): number => {
    const time = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(time);
    let sum = 0;
    for (const sample of time) {
      const centered = (sample - 128) / 128;
      sum += centered * centered;
    }
    const rms = Math.sqrt(sum / time.length);
    const rate = rms > smoothMouth ? 0.45 : 0.18;
    smoothMouth = smoothMouth + (rms - smoothMouth) * rate;
    return Math.min(1, smoothMouth * 3.2);
  };

  let curve: ProtoCurve | null = null;
  let curveStart = 0;
  let raf = 0;
  let last = performance.now();
  const frame = (now: number) => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    const params = blendParams("日常", 0.55, now / 1000, readMouth());
    if (curve) {
      const offsets = curve.offsetAt((now - curveStart) / 1000);
      if (offsets === null) curve = null;
      else for (const [key, value] of Object.entries(offsets)) params[key] = (params[key] ?? 0) + value;
    }
    renderer.setParameters(params);
    void dt;
    raf = requestAnimationFrame(frame);
  };

  const ttsCache = new Map<string, { url: string; durationMs: number }>();
  const fetchTts = async (text: string) => {
    const cached = ttsCache.get(text);
    if (cached) return cached;
    say(`合成 TTS：${text}`);
    const res = await fetch("/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error(`/tts ${res.status}`);
    const buf = new Uint8Array(await (await res.blob()).arrayBuffer());
    const item = { url: URL.createObjectURL(new Blob([buf], { type: "audio/wav" })), durationMs: wavDurationMs(buf) };
    ttsCache.set(text, item);
    return item;
  };

  let selected = SENTENCES[1]; // 默认中句（2.83s，现状覆盖最不足的典型）

  const play = (makeCurve: (durationMs: number) => ProtoCurve, label: string) => {
    void (async () => {
      try {
        // resume 不等待：无手势环境（无头测试）下 promise 可能长挂，曲线与音频不该被它阻塞
        if (actx.state === "suspended") void actx.resume();
        const audio = await fetchTts(selected.text);
        audioEl.src = audio.url;
        curve = makeCurve(audio.durationMs);
        curveStart = performance.now();
        await audioEl.play();
        say(`${label}｜${selected.label}｜音频 ${audio.durationMs}ms｜${curve.describe}`);
      } catch (error) {
        say(`播放失败：${String(error)}`);
      }
    })();
  };

  void renderer.load(manifest.model_url!).then(() => {
    const sentenceRow = row("句子");
    for (const s of SENTENCES) {
      const btn = el("button", s.label.split("「")[0]);
      if (s === selected) btn.classList.add("active");
      btn.onclick = () => {
        selected = s;
        sentenceRow.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
        say(`已选 ${s.label}（会自动预合成）`);
        void fetchTts(s.text).catch((e) => say(`预合成失败：${String(e)}`));
      };
      sentenceRow.append(btn);
    }
    void fetchTts(selected.text).catch(() => {});

    const demoRow = row("对比");
    const cases: Array<[string, (ms: number) => ProtoCurve]> = [
      ["现状·点头", (_ms) => currentCurve("点头")],
      ["提案·点头×N", (ms) => repeatedCurve("点头", ms)],
      ["提案·摇头×N", (ms) => repeatedCurve("摇头", ms)],
      ["提案·歪头·保持", (ms) => holdCurve("歪头", ms)],
      ["现状·摇头", () => currentCurve("摇头")],
      ["现状·歪头", () => currentCurve("歪头")],
    ];
    for (const [label, make] of cases) {
      const btn = el("button", label);
      btn.onclick = () => play(make, label);
      demoRow.append(btn);
    }
    controls.append(sentenceRow, demoRow);
    say("模型就绪。选句子后点对比按钮：音频播放的同时跑曲线，看头在不在说话窗口里。");
  }).catch((error) => {
    status.className = "status err";
    say(`挂载失败：${String(error)}`);
  });

  raf = requestAnimationFrame(frame);
  window.addEventListener("pagehide", () => {
    cancelAnimationFrame(raf);
    renderer.destroy();
    void actx.close();
  });
}

function ensureCore(coreUrl: string): Promise<void> {
  if (corePromise) return corePromise;
  const existing = (window as unknown as { Live2DCubismCore?: unknown }).Live2DCubismCore;
  if (existing) {
    corePromise = Promise.resolve();
    return corePromise;
  }
  corePromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = coreUrl;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Cubism Core 加载失败"));
    document.head.appendChild(script);
  });
  return corePromise;
}

main().catch((error) => {
  const status = document.getElementById("status-app");
  if (status) {
    status.className = "status err";
    status.textContent = `初始化失败：${String(error)}`;
  }
});
