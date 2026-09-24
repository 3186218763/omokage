import { useCallback, useEffect, useRef, useState } from "react";
import type { PlaybackEvent } from "../playback/director";

const BAR_COUNT = 24;
const MIN_BAR = 4;
export interface QueueItem {
  key: string;
  url: string;
  turnId?: string;
  index?: number;
  pauseMs?: number;
}

function createAudioContext(): AudioContext | null {
  const Ctor = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  return Ctor ? new Ctor() : null;
}
function formatTime(seconds: number): string {
  const n = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(n / 60)}:${(n % 60).toString().padStart(2, "0")}`;
}

export function useAudioQueue(options?: {
  onRms?: (value: number) => void;
  onPlayback?: (event: PlaybackEvent) => void;
}) {
  const callbacks = useRef(options);
  callbacks.current = options;
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [holding, setHolding] = useState(false);
  const [waveform, setWaveform] = useState<number[]>(Array(BAR_COUNT).fill(MIN_BAR));
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const pending = useRef<QueueItem[]>([]);
  const seen = useRef(new Set<string>());
  const current = useRef<{ item: QueueItem; audio: HTMLAudioElement; source?: MediaElementAudioSourceNode } | null>(null);
  const ctx = useRef<AudioContext | null>(null);
  const analyser = useRef<AnalyserNode | null>(null);
  const gain = useRef<GainNode | null>(null);
  const fade = useRef<number | null>(null);
  const pauseTimer = useRef<number | null>(null);
  const mouthLevel = useRef(0);
  const mouthRelease = useRef<number | null>(null);
  const fading = useRef(false);
  const next = useRef<() => void>(() => {});

  const release = useCallback(() => {
    const old = current.current;
    current.current = null; // invalidate media events before pausing/releasing src
    if (old) {
      old.audio.pause();
      old.audio.removeAttribute("src");
      old.audio.load();
      old.source?.disconnect();
    }
    if (mouthRelease.current !== null) cancelAnimationFrame(mouthRelease.current);
    const start = performance.now();
    const from = mouthLevel.current;
    const settleMouth = (now: number) => {
      const progress = Math.min(1, (now - start) / 200);
      const eased = progress * progress * (3 - 2 * progress);
      mouthLevel.current = from * (1 - eased);
      callbacks.current?.onRms?.(mouthLevel.current);
      mouthRelease.current = progress < 1 ? requestAnimationFrame(settleMouth) : null;
    };
    if (from > 0 && old) mouthRelease.current = requestAnimationFrame(settleMouth);
    else { mouthLevel.current = 0; callbacks.current?.onRms?.(0); mouthRelease.current = null; }
    setActiveKey(null);
    setIsPlaying(false);
  }, []);

  const clear = useCallback(() => {
    if (mouthRelease.current !== null) cancelAnimationFrame(mouthRelease.current);
    mouthRelease.current = null;
    if (pauseTimer.current !== null) window.clearTimeout(pauseTimer.current);
    pauseTimer.current = null;
    setHolding(false);
    if (fade.current !== null) window.clearTimeout(fade.current);
    fade.current = null;
    fading.current = false;
    pending.current = [];
    seen.current.clear();
    release();
    if (mouthRelease.current !== null) cancelAnimationFrame(mouthRelease.current);
    mouthRelease.current = null;
    mouthLevel.current = 0;
    callbacks.current?.onRms?.(0);
    if (gain.current && ctx.current) {
      gain.current.gain.cancelScheduledValues(ctx.current.currentTime);
      gain.current.gain.setValueAtTime(1, ctx.current.currentTime);
    }
    setCurrentTime(0);
    setDuration(0);
  }, [release]);

  useEffect(() => {
    const context = createAudioContext();
    ctx.current = context;
    if (context) {
      const meter = context.createAnalyser();
      meter.fftSize = 64;
      const volume = context.createGain();
      // Meter follows gain so fading and the mouth share the same signal.
      volume.connect(meter);
      meter.connect(context.destination);
      gain.current = volume;
      analyser.current = meter;
    }
    return () => {
      clear();
      void context?.close();
      ctx.current = null;
      gain.current = null;
      analyser.current = null;
    };
  }, [clear]);

  const play = useCallback((item: QueueItem) => {
    release();
    const audio = new Audio(item.url);
    audio.preload = "auto";
    const context = ctx.current;
    const source = context && gain.current ? context.createMediaElementSource(audio) : undefined;
    if (source && gain.current) source.connect(gain.current);
    const entry = { item, audio, source };
    current.current = entry;
    setActiveKey(item.key);
    setCurrentTime(0);
    setDuration(0);
    const valid = () => current.current === entry;
    const emit = (type: PlaybackEvent["type"]) => {
      if (valid() && item.turnId !== undefined && item.index !== undefined) {
        callbacks.current?.onPlayback?.({ type, turnId: item.turnId, index: item.index,
          currentTime: audio.currentTime, duration: audio.duration });
      }
    };
    audio.addEventListener("playing", () => {
      if (!valid() || fading.current) return;
      if (mouthRelease.current !== null) cancelAnimationFrame(mouthRelease.current);
      mouthRelease.current = null;
      setIsPlaying(true);
      emit("playing");
    });
    for (const name of ["pause", "waiting"] as const) audio.addEventListener(name, () => {
      if (!valid()) return;
      if (name === "pause" && audio.ended) return;
      setIsPlaying(false);
      callbacks.current?.onRms?.(0);
      mouthLevel.current = 0;
      emit("paused");
    });
    audio.addEventListener("durationchange", () => {
      if (valid()) setDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
    });
    audio.addEventListener("timeupdate", () => { if (valid()) setCurrentTime(audio.currentTime); });
    const finish = (type: "ended" | "failed") => {
      if (!valid()) return;
      emit(type);
      release();
      if (!fading.current) next.current();
    };
    audio.addEventListener("ended", () => finish("ended"));
    audio.addEventListener("error", () => finish("failed"));
    if (context?.state === "suspended") void context.resume().catch(() => {});
    void audio.play().catch(() => {
      if (valid()) { setIsPlaying(false); emit("paused"); }
    });
  }, [release]);
  next.current = () => {
    if (current.current || fading.current || pauseTimer.current !== null) return;
    const item = pending.current.shift();
    if (!item) return;
    if ((item.pauseMs ?? 0) > 0) {
      setHolding(true);
      pauseTimer.current = window.setTimeout(() => {
        pauseTimer.current = null;
        setHolding(false);
        play(item);
      }, item.pauseMs);
    } else play(item);
  };

  const enqueue = useCallback((item: QueueItem) => {
    if (!item.url || seen.current.has(item.key)) return;
    seen.current.add(item.key);
    pending.current.push(item);
    next.current();
  }, []);
  const fadeStop = useCallback(() => {
    pending.current = [];
    if (pauseTimer.current !== null) {
      window.clearTimeout(pauseTimer.current);
      pauseTimer.current = null;
      setHolding(false);
    }
    if (fading.current) return;
    if (!ctx.current || !gain.current || !current.current) { clear(); return; }
    fading.current = true;
    const now = ctx.current.currentTime;
    gain.current.gain.cancelScheduledValues(now);
    gain.current.gain.setValueAtTime(gain.current.gain.value, now);
    gain.current.gain.linearRampToValueAtTime(0, now + 0.2);
    fade.current = window.setTimeout(clear, 230);
  }, [clear]);
  const toggle = useCallback((item: QueueItem) => {
    const entry = current.current;
    if (entry?.item.key === item.key) {
      if (!entry.audio.paused) entry.audio.pause();
      else {
        void ctx.current?.resume().catch(() => {});
        void entry.audio.play().catch(() => {});
      }
    } else {
      clear();
      play(item); // one saved line starts now; the beat only lives between queued lines
    }
  }, [clear, play]);

  useEffect(() => {
    if (!isPlaying) return;
    let raf = 0;
    let smooth = 0;
    const tick = () => {
      const entry = current.current;
      if (entry && !entry.audio.paused) {
        const { item, audio } = entry;
        if (item.turnId !== undefined && item.index !== undefined) {
          callbacks.current?.onPlayback?.({ type: "clock", turnId: item.turnId, index: item.index,
            currentTime: audio.currentTime, duration: audio.duration });
        }
        const meter = analyser.current;
        if (meter) {
          const data = new Uint8Array(meter.frequencyBinCount);
          meter.getByteFrequencyData(data);
          setWaveform(Array.from({ length: BAR_COUNT }, (_, i) => Math.max(MIN_BAR, Math.round(data[Math.floor(i * data.length / BAR_COUNT)] / 255 * 100))));
          const samples = new Uint8Array(meter.fftSize);
          meter.getByteTimeDomainData(samples);
          const rms = Math.sqrt(samples.reduce((sum, value) => sum + ((value - 128) / 128) ** 2, 0) / samples.length);
          smooth += (rms - smooth) * (rms > smooth ? 0.45 : 0.18);
          mouthLevel.current = Math.min(1, smooth * 3.2);
          callbacks.current?.onRms?.(mouthLevel.current);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [isPlaying]);

  return { enqueue, clear, fadeStop, toggle, activeKey, isPlaying, holding, waveform, duration, currentTime, formatTime };
}
