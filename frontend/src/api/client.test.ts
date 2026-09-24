import { expect, it } from "vitest";
import { isChatEvent } from "./client";
it("rejects malformed indices, nonfinite values and unknown control labels", () => {
  const base = { v: 2, turn_id: "one" };
  expect(isChatEvent({ ...base, type: "sentence", index: 0, motion: "点头", text: "你好" })).toBe(true);
  expect(isChatEvent({ ...base, type: "sentence", index: -1, motion: null, text: "你好" })).toBe(false);
  expect(isChatEvent({ ...base, type: "sentence", index: 0, motion: "挥手", text: "你好" })).toBe(false);
  expect(isChatEvent({ ...base, type: "audio", index: .5, audio: "a" })).toBe(false);
  expect(isChatEvent({ ...base, type: "performance", revision: 1, emotion: "温柔", intensity: NaN, confidence: .8, source: "kev", decay_ms: 0 })).toBe(false);
  expect(isChatEvent({ type: "done" })).toBe(false);
  expect(isChatEvent({ ...base, type: "storage_warning", message: "本轮未保存" })).toBe(true);
});
