export interface PlaybackSample { turn_id: string; event: string; index?: number; ms: number }
const samples: PlaybackSample[] = [];
/** Bounded, local-only diagnostics; never records dialogue or audio. */
export function recordPlayback(turnId: string, event: string, index?: number): void {
  samples.push({ turn_id: turnId, event, index, ms: performance.now() });
  if (samples.length > 10000) samples.splice(0, samples.length - 10000);
}
export function playbackSamples(): PlaybackSample[] { return samples.map((sample) => ({ ...sample })); }
if (typeof window !== "undefined") {
  Object.assign(window, { omokagePlaybackSamples: playbackSamples });
}
