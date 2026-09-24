import { MOTION_DURATIONS, MOTIONS, type ChatEvent } from "../types";

export type PerformanceEvent = Extract<ChatEvent, { type: "performance" }>;
export type PlaybackEvent = {
  type: "playing" | "paused" | "ended" | "failed" | "clock";
  turnId: string;
  index: number;
  currentTime: number;
  duration: number;
};
export type Effect =
  | { type: "idle" | "stopMotion" }
  | { type: "performance"; value: PerformanceEvent }
  | { type: "motion"; name: string; duration: number; currentTime: number; index: number }
  | { type: "clock"; currentTime: number };

/** Generation completion does not close playback. No DOM, timers or audio ownership here. */
export class PlaybackDirector {
  turnId = "";
  closed = true;
  private done = false;
  private count = 0;
  private finished = new Set<number>();
  private motions = new Map<number, (typeof MOTIONS)[number]>();
  private triggered = new Set<number>();
  private performance?: PerformanceEvent;
  private fallback?: PerformanceEvent;
  private revision = -1;
  private active: number | null = null;
  private playing = false;
  private surpriseDeadline: number | null = null;
  private appliedRevision = -1;

  constructor(private now: () => number = () => performance.now()) {}

  start(turnId: string): Effect[] {
    this.turnId = turnId;
    this.closed = false;
    this.done = false;
    this.count = 0;
    this.finished.clear();
    this.motions.clear();
    this.triggered.clear();
    this.performance = undefined;
    this.fallback = undefined;
    this.revision = -1;
    this.appliedRevision = -1;
    this.active = null;
    this.playing = false;
    this.surpriseDeadline = null;
    return [{ type: "idle" }];
  }

  cancel(): Effect[] {
    this.closed = true;
    this.active = null;
    this.surpriseDeadline = null;
    return [{ type: "idle" }];
  }

  private apply(): Effect[] {
    if (!this.performance || this.appliedRevision === this.revision) return [];
    this.appliedRevision = this.revision;
    this.surpriseDeadline = this.performance.emotion === "惊讶" ? this.now() + 1200 : null;
    return [{ type: "performance", value: this.performance }];
  }

  private drain(): Effect[] {
    if (this.done && this.finished.size >= this.count) return this.cancel();
    return [];
  }

  dispatch(event: ChatEvent | PlaybackEvent): Effect[] {
    const turn = "turnId" in event ? event.turnId : event.turn_id;
    if (this.closed || turn !== this.turnId) return [];
    switch (event.type) {
      case "sentence":
        this.count = Math.max(this.count, event.index + 1);
        if (event.motion) this.motions.set(event.index, event.motion);
        return [];
      case "performance":
        if (event.revision <= this.revision) return [];
        this.revision = event.revision;
        this.performance = event;
        if (event.source === "speaking_style") this.fallback = event;
        return this.playing ? this.apply() : [];
      case "playing": {
        this.active = event.index;
        this.playing = true;
        const effects = this.apply();
        const name = this.motions.get(event.index);
        if (!this.triggered.has(event.index)) {
          this.triggered.add(event.index);
          if (name) {
            const curveDuration = MOTION_DURATIONS[name];
            const remaining = event.duration - event.currentTime;
            // `playing` may arrive before metadata has populated duration.
            // Start from the media clock anyway; a later ended event stops it
            // if the clip is too short to contain the full curve.
            const durationKnown = Number.isFinite(event.duration) && event.duration > 0;
            const duration = durationKnown ? Math.min(curveDuration, remaining) : curveDuration;
            if (!durationKnown || remaining >= 0.25) {
              effects.push({ type: "motion", name, index: event.index, duration, currentTime: event.currentTime });
            }
          }
        }
        return effects;
      }
      case "clock": {
        if (this.active !== event.index || !this.playing) return [];
        const effects: Effect[] = [{ type: "clock", currentTime: event.currentTime }];
        if (this.surpriseDeadline !== null && this.now() >= this.surpriseDeadline) {
          this.surpriseDeadline = null;
          const base = this.fallback?.emotion !== "惊讶" ? this.fallback : undefined;
          if (this.performance) {
            this.performance = { ...this.performance, emotion: base?.emotion ?? "日常", intensity: base?.intensity ?? 0.55, decay_ms: 0 };
            effects.push({ type: "performance", value: this.performance });
          }
        }
        return effects;
      }
      case "paused":
        this.playing = false;
        return [];
      case "ended":
      case "failed":
      case "audio_error":
        this.finished.add(event.index);
        const wasActive = this.active === event.index;
        if (wasActive) {
          this.active = null;
          this.playing = false;
        }
        return [...(wasActive ? [{ type: "stopMotion" } as const] : []), ...this.drain()];
      case "done":
        this.done = true;
        this.count = event.sentence_count;
        return this.drain();
      case "interrupted":
      case "error":
        return this.cancel();
      default:
        return [];
    }
  }
}
