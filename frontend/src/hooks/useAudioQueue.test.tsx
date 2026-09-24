import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAudioQueue, type QueueItem } from "./useAudioQueue";

class FakeAudio extends EventTarget {
  static instances: FakeAudio[] = [];
  static reject = false;
  paused = true;
  ended = false;
  duration = 2;
  currentTime = 0;
  preload = "";
  src: string;
  constructor(src: string) { super(); this.src = src; FakeAudio.instances.push(this); }
  play = vi.fn(() => FakeAudio.reject ? Promise.reject(new Error("blocked")) : Promise.resolve());
  pause() { this.paused = true; this.dispatchEvent(new Event("pause")); }
  load() {}
  removeAttribute() {}
  playing() { this.paused = false; this.dispatchEvent(new Event("playing")); }
}
const item = (index: number): QueueItem => ({ key: `one:${index}`, url: `audio-${index}`, turnId: "one", index });
beforeEach(() => { FakeAudio.instances = []; FakeAudio.reject = false; vi.stubGlobal("Audio", FakeAudio); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("does not announce playback before playing; consumes a burst in order, never the last item first", async () => {
  const onPlayback = vi.fn();
  const { result } = renderHook(() => useAudioQueue({ onPlayback }));
  act(() => { result.current.enqueue(item(0)); result.current.enqueue(item(1)); result.current.enqueue(item(2)); });
  expect(FakeAudio.instances).toHaveLength(1);
  expect(onPlayback).not.toHaveBeenCalled();
  const first = FakeAudio.instances[0];
  act(() => first.playing());
  expect(onPlayback.mock.calls[0][0].type).toBe("playing");
  act(() => first.dispatchEvent(new Event("ended")));
  expect(FakeAudio.instances[1].src).toBe("audio-1");
  act(() => FakeAudio.instances[1].dispatchEvent(new Event("error")));
  expect(FakeAudio.instances[2].src).toBe("audio-2");
  act(() => result.current.enqueue(item(2)));
  expect(FakeAudio.instances).toHaveLength(3);
});
it("keeps rejected audio for a user gesture and ignores events from released elements", async () => {
  FakeAudio.reject = true;
  const onPlayback = vi.fn();
  const { result } = renderHook(() => useAudioQueue({ onPlayback }));
  await act(async () => result.current.enqueue(item(0)));
  expect(onPlayback.mock.calls.map(([e]) => e.type)).toEqual(["paused"]);
  const first = FakeAudio.instances[0];
  act(() => result.current.clear());
  act(() => first.playing());
  expect(onPlayback.mock.calls.map(([e]) => e.type)).toEqual(["paused"]);
});
it("pause/resume uses the existing media position instead of restarting", () => {
  const { result } = renderHook(() => useAudioQueue());
  act(() => result.current.enqueue(item(0)));
  const first = FakeAudio.instances[0];
  act(() => first.playing());
  first.currentTime = .5;
  act(() => result.current.toggle(item(0)));
  act(() => result.current.toggle(item(0)));
  expect(FakeAudio.instances).toHaveLength(1);
  expect(first.currentTime).toBe(.5);
  expect(first.play).toHaveBeenCalledTimes(2);
});

it("delays only the tagged sentence and cancels pending silence on clear", () => {
  vi.useFakeTimers();
  try {
    const { result } = renderHook(() => useAudioQueue());
    act(() => result.current.enqueue({ ...item(0), pauseMs: 300 }));
    expect(result.current.holding).toBe(true);
    expect(FakeAudio.instances).toHaveLength(0);
    act(() => vi.advanceTimersByTime(299));
    expect(FakeAudio.instances).toHaveLength(0);
    act(() => vi.advanceTimersByTime(1));
    expect(result.current.holding).toBe(false);
    expect(FakeAudio.instances).toHaveLength(1);
    act(() => result.current.enqueue({ ...item(1), pauseMs: 700 }));
    act(() => FakeAudio.instances[0].dispatchEvent(new Event("ended")));
    expect(FakeAudio.instances).toHaveLength(1);
    act(() => result.current.clear());
    expect(result.current.holding).toBe(false);
    act(() => vi.advanceTimersByTime(700));
    expect(FakeAudio.instances).toHaveLength(1);
  } finally { vi.useRealTimers(); }
});

it("starts a saved line immediately and skips a clip that never arrived", () => {
  vi.useFakeTimers();
  try {
    const { result } = renderHook(() => useAudioQueue());
    act(() => result.current.toggle({ ...item(0), pauseMs: 1200 }));
    expect(FakeAudio.instances).toHaveLength(1);
    expect(result.current.holding).toBe(false);
    act(() => result.current.enqueue({ ...item(1), url: "", pauseMs: 1200 }));
    act(() => vi.advanceTimersByTime(1200));
    expect(FakeAudio.instances).toHaveLength(1);
    expect(result.current.holding).toBe(false);
  } finally { vi.useRealTimers(); }
});

it("releases mouth smoothly after playback ends", () => {
  const frames = new Map<number, FrameRequestCallback>();
  let frameId = 0;
  let now = 0;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frames.set(++frameId, callback); return frameId; });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => { frames.delete(id); });
  class FakeContext {
    state = "running";
    destination = {};
    createAnalyser() { return {
      fftSize: 64, frequencyBinCount: 32, connect() {},
      getByteFrequencyData(data: Uint8Array) { data.fill(0); },
      getByteTimeDomainData(data: Uint8Array) { data.fill(255); },
    }; }
    createGain() { return { gain: { value: 1, cancelScheduledValues() {}, setValueAtTime() {}, linearRampToValueAtTime() {} }, connect() {} }; }
    createMediaElementSource() { return { connect() {}, disconnect() {} }; }
    close() { return Promise.resolve(); }
  }
  vi.stubGlobal("AudioContext", FakeContext);
  const onRms = vi.fn();
  const { result } = renderHook(() => useAudioQueue({ onRms }));
  act(() => result.current.enqueue(item(0)));
  act(() => FakeAudio.instances[0].playing());
  const firstFrame = [...frames.entries()][0];
  act(() => { frames.delete(firstFrame[0]); firstFrame[1](now); });
  const voiced = onRms.mock.lastCall?.[0] as number;
  expect(voiced).toBeGreaterThan(0);
  FakeAudio.instances[0].ended = true;
  act(() => FakeAudio.instances[0].dispatchEvent(new Event("pause")));
  expect(onRms.mock.lastCall?.[0]).toBe(voiced);
  act(() => FakeAudio.instances[0].dispatchEvent(new Event("ended")));
  expect(onRms.mock.lastCall?.[0]).toBe(voiced);
  const releaseFrame = [...frames.entries()].at(-1);
  expect(releaseFrame).toBeDefined();
  now = 200;
  act(() => { frames.delete(releaseFrame![0]); releaseFrame![1](now); });
  expect(onRms.mock.lastCall?.[0]).toBe(0);
});
