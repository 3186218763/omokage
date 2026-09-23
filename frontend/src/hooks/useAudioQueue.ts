import { useCallback, useEffect, useRef, useState } from "react";

const BAR_COUNT = 24;
const MIN_BAR = 4;

export interface QueueItem {
  key: string; // `${messageId}:${index}`
  url: string;
  motion?: string; // 该音频对应句的动作；音频起播瞬间触发，锚定播放窗口
}

function createAudioContext(): AudioContext | null {
  const Ctor =
    window.AudioContext ??
    (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  return Ctor ? new Ctor() : null;
}

function formatTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function useAudioQueue(options?: {
  onRms?: (value: number) => void;
  onItemStart?: (item: QueueItem) => void;
}) {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [waveform, setWaveform] = useState<number[]>(() =>
    Array.from({ length: BAR_COUNT }, () => MIN_BAR),
  );
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);

  const onRmsRef = useRef(options?.onRms);
  onRmsRef.current = options?.onRms;
  const onItemStartRef = useRef(options?.onItemStart);
  onItemStartRef.current = options?.onItemStart;
  const smoothRef = useRef(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const itemsRef = useRef<QueueItem[]>([]);
  const activeRef = useRef<string | null>(null);
  const gainRef = useRef<GainNode | null>(null);
  const fadeTimerRef = useRef<number | null>(null);

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);
  useEffect(() => {
    activeRef.current = activeKey;
  }, [activeKey]);

  // 一次性初始化：audio 元素 + 音频图（source→analyser→gain→destination）。
  // gain 只为淡出服务：平时恒为 1。
  useEffect(() => {
    const audio = new Audio();
    audio.preload = "auto";
    audioRef.current = audio;
    const ctx = createAudioContext();
    ctxRef.current = ctx;
    if (ctx) {
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.8;
      const gain = ctx.createGain();
      gain.gain.value = 1;
      gainRef.current = gain;
      const source = ctx.createMediaElementSource(audio);
      source.connect(analyser);
      analyser.connect(gain);
      gain.connect(ctx.destination); // 不连 destination 会完全无声
      analyserRef.current = analyser;
    }
    audio.addEventListener("durationchange", () => setDuration(audio.duration || 0));
    audio.addEventListener("timeupdate", () => setCurrentTime(audio.currentTime));
    audio.addEventListener("ended", () => playNextRef.current());
    audio.addEventListener("error", () => {
      setActiveKey(null);
      setIsPlaying(false);
    });
    return () => {
      audio.pause();
      audio.removeAttribute("src");
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      void ctx?.close();
    };
  }, []);

  const playItem = useCallback((item: QueueItem) => {
    const audio = audioRef.current;
    if (!audio || item.url === "") return;
    const ctx = ctxRef.current;
    if (ctx && ctx.state === "suspended") void ctx.resume(); // 用户手势解锁
    setCurrentTime(0);
    setActiveKey(item.key);
    audio.src = item.url;
    onItemStartRef.current?.(item);
    audio.play()
      .then(() => setIsPlaying(true))
      .catch(() => setIsPlaying(false)); // 自动播放被拦截：停留为暂停态，点击可重播
  }, []);

  const playNextRef = useRef<() => void>(() => {});
  playNextRef.current = () => {
    const list = itemsRef.current;
    const cur = activeRef.current;
    const index = list.findIndex((item) => item.key === cur);
    const next = list[index + 1];
    if (next) playItem(next);
    else {
      setActiveKey(null);
      setIsPlaying(false);
    }
  };

  const clear = useCallback(() => {
    if (fadeTimerRef.current !== null) {
      window.clearTimeout(fadeTimerRef.current);
      fadeTimerRef.current = null;
    }
    itemsRef.current = [];
    activeRef.current = null;
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    const ctx = ctxRef.current;
    const gain = gainRef.current;
    if (ctx && gain) {
      const now = ctx.currentTime;
      gain.gain.cancelScheduledValues(now);
      gain.gain.setValueAtTime(1, now); // 恢复增益，下一轮正常出声
    }
    setItems([]);
    setActiveKey(null);
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);
  }, []);

  const enqueue = useCallback(
    (item: QueueItem) => {
      if (fadeTimerRef.current !== null) {
        // 淡出还没走完就来了新音频：立即完成清空，别让随后的定时器把新条目一并吞掉
        clear();
      }
      setItems((prev) =>
        prev.some((existing) => existing.key === item.key) ? prev : [...prev, item],
      );
    },
    [clear],
  );

  /** 让路用：~200ms 增益斜坡淡出后清空队列，不是硬切。 */
  const fadeStop = useCallback(() => {
    const ctx = ctxRef.current;
    const gain = gainRef.current;
    if (!ctx || !gain) {
      clear();
      return;
    }
    const now = ctx.currentTime;
    gain.gain.cancelScheduledValues(now);
    gain.gain.setValueAtTime(gain.gain.value, now);
    gain.gain.linearRampToValueAtTime(0, now + 0.2);
    fadeTimerRef.current = window.setTimeout(() => {
      fadeTimerRef.current = null;
      clear();
    }, 230);
  }, [clear]);

  // 队列首次获得条目时自动播放（enqueue 只入队，播放由本 effect 驱动）；
  // 播放中/用户手动暂停时 activeRef 非 null 会跳过，不打断用户控制。
  useEffect(() => {
    const first = items[0];
    if (!first) return;
    if (activeRef.current === null && audioRef.current?.paused) {
      playItem(first);
    }
  }, [items, playItem]);

  const toggle = useCallback(
    (item: QueueItem) => {
      if (activeRef.current === item.key && audioRef.current && !audioRef.current.paused) {
        audioRef.current.pause();
        setIsPlaying(false);
        return;
      }
      playItem(item);
    },
    [playItem],
  );

  // 波形采样与口型 RMS：仅播放中持续 rAF。停播时嘴回到 0。
  useEffect(() => {
    if (!isPlaying) {
      smoothRef.current = 0;
      onRmsRef.current?.(0);
      return;
    }
    let raf = 0;
    const tick = () => {
      const analyser = analyserRef.current;
      if (analyser) {
        const data = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(data);
        setWaveform(
          Array.from({ length: BAR_COUNT }, (_, i) => {
            const source = Math.floor((i / BAR_COUNT) * data.length);
            return Math.max(MIN_BAR, Math.round((data[source] / 255) * 100));
          }),
        );
        const time = new Uint8Array(analyser.fftSize);
        analyser.getByteTimeDomainData(time);
        let sum = 0;
        for (const sample of time) {
          const centered = (sample - 128) / 128;
          sum += centered * centered;
        }
        const rms = Math.sqrt(sum / time.length);
        const previous = smoothRef.current;
        const rate = rms > previous ? 0.45 : 0.18;
        const smooth = previous + (rms - previous) * rate;
        smoothRef.current = smooth;
        onRmsRef.current?.(Math.min(1, smooth * 3.2));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [isPlaying]);

  return {
    enqueue,
    clear,
    fadeStop,
    toggle,
    activeKey,
    isPlaying,
    waveform,
    duration,
    currentTime,
    formatTime,
  };
}
