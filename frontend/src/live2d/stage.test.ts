import { afterEach, beforeEach, expect, it, vi } from "vitest";
const fake = vi.hoisted(() => ({ setParameters: vi.fn(), runtimeAvailable: false, reset: vi.fn(), destroy: vi.fn() }));
vi.mock("@soullink-emotion/live2d-pixi", () => ({ Live2DRenderer: class {
  load = async () => ({ ParamAngleY: { min: -3, max: 3, default: 0 }, ParamMouthOpenY: { min: 0, max: .8, default: 0 } });
  setParameters = fake.setParameters;
  destroy = fake.destroy;
} }));
vi.mock("@soullink-emotion/engine", () => ({
  loadModelProfile: async () => { if (!fake.runtimeAvailable) throw new Error("missing"); return { profile: {} }; },
  SoullinkRuntime: class {
    setIdleEnabled() {} setLipSyncEnabled() {} triggerIntent() {} setAudioLevelAnalyzer() {}
    update() { return { live2dParams: { ParamAngleY: 1, ParamMouthOpenY: .4, MissingParameter: 50 } }; }
    reset = fake.reset;
  },
}));
import { mountStage } from "./stage";
let frame: FrameRequestCallback;
let now = 0;
beforeEach(() => {
  fake.setParameters.mockClear(); fake.runtimeAvailable = false; now = 0;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frame = callback; return 1; });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it.each([false, true])("limits actual model parameters and keeps motion on the media clock (runtime=%s)", async (runtime) => {
  fake.runtimeAvailable = runtime;
  const stage = await mountStage(document.createElement("div"), { model_url: "model", core_url: "core" });
  stage.setMouth(1); stage.playMotion("点头", .8, 0); stage.setMotionTime(.4);
  now = 1000; frame(now);
  expect(fake.setParameters.mock.lastCall?.[0]).toEqual({ ParamAngleY: -3, ParamMouthOpenY: .8 });
  now = 5000; frame(now); // wall time must not finish a paused media-clock motion
  expect(fake.setParameters.mock.lastCall?.[0].ParamAngleY).toBe(-3);
  stage.stopMotion(); stage.setMouth(0); now += 16; frame(now);
  expect(fake.setParameters.mock.lastCall?.[0].ParamAngleY).toBeGreaterThan(-3);
  expect(fake.setParameters.mock.lastCall?.[0].ParamMouthOpenY).toBe(0);
  stage.resetIdle(); stage.destroy();
  expect(fake.destroy).toHaveBeenCalled();
});
