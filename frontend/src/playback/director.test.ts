import { describe, expect, it } from "vitest";
import { PlaybackDirector, type PerformanceEvent, type PlaybackEvent } from "./director";
const base = { v: 2 as const, turn_id: "one" };
const perf = (revision = 0, emotion = "温柔"): PerformanceEvent => ({ ...base, type: "performance", revision, emotion,
  intensity: 0.9, confidence: 0.8, source: revision ? "kev" : "speaking_style", decay_ms: 0 });
const media = (type: PlaybackEvent["type"], index = 0, duration = 2): PlaybackEvent => ({ type, turnId: "one", index, duration, currentTime: 0 });
function setup() {
  const director = new PlaybackDirector(); director.start("one");
  director.dispatch({ ...base, type: "sentence", index: 0, text: "你好", motion: "点头" });
  return director;
}
describe("playback control", () => {
  it("caches Kev until actual playing and does not drain on generation done", () => {
    const d = setup();
    expect(d.dispatch(perf())).toEqual([]);
    expect(d.dispatch(perf(1, "俏皮"))).toEqual([]);
    expect(d.dispatch({ ...base, type: "done", sentence_count: 1 })).toEqual([]);
    const effects = d.dispatch(media("playing"));
    expect(effects.map(e => e.type)).toEqual(["performance", "motion"]);
    expect(d.dispatch(media("playing"))).toEqual([]);
    expect(d.dispatch(media("ended")).map(e => e.type)).toEqual(["stopMotion", "idle"]);
    expect(d.dispatch(perf(2))).toEqual([]);
  });
  it("does not move on rejection, re-trigger on resume, or move for short clips", () => {
    const d = setup();
    expect(d.dispatch(media("paused"))).toEqual([]);
    expect(d.dispatch(media("playing", 0, .1))).toEqual([]);
    d.dispatch(media("paused"));
    expect(d.dispatch(media("playing"))).toEqual([]);
  });
  it("starts a sentence motion when the browser has not reported duration yet", () => {
    const d = setup();
    const effects = d.dispatch({ ...media("playing"), duration: Number.NaN });
    expect(effects).toContainEqual({
      type: "motion", name: "点头", index: 0, duration: .8, currentTime: 0,
    });
  });
  it("plays the same motion again for a later sentence in the same turn", () => {
    const d = setup();
    d.dispatch({ ...base, type: "sentence", index: 1, text: "又摇头", motion: "点头" });
    expect(d.dispatch(media("playing", 0)).some((effect) => effect.type === "motion")).toBe(true);
    d.dispatch(media("ended", 0));
    expect(d.dispatch(media("playing", 1)).some((effect) => effect.type === "motion")).toBe(true);
  });
  it("ignores old turns, duplicate revisions and cancelled media", () => {
    const d = setup(); d.dispatch(perf(1));
    expect(d.dispatch(perf(0))).toEqual([]);
    d.cancel(); expect(d.dispatch(media("playing"))).toEqual([]);
    d.start("two"); expect(d.dispatch(perf(2))).toEqual([]);
  });
  it("surprise returns to this turn's fallback and never the prior turn", () => {
    let now = 0; const d = new PlaybackDirector(() => now); d.start("one");
    d.dispatch(perf()); d.dispatch(perf(1, "惊讶"));
    d.dispatch(media("playing")); now = 1300;
    const effects = d.dispatch(media("clock"));
    expect(effects).toContainEqual({ type: "performance", value: { ...perf(1, "温柔"), intensity: .9 } });
    d.start("two");
    d.dispatch({ ...perf(1, "惊讶"), turn_id: "two" });
    d.dispatch({ ...media("playing"), turnId: "two" }); now += 1300;
    const next = d.dispatch({ ...media("clock"), turnId: "two" }).find(e => e.type === "performance");
    expect(next?.type === "performance" && next.value.emotion).toBe("日常");
  });
  it("TTS failures count toward draining but cannot stop another sentence's motion", () => {
    const d = setup(); d.dispatch(media("playing"));
    expect(d.dispatch({ ...base, type: "audio_error", index: 1, message: "failed" })).toEqual([]);
  });
});
