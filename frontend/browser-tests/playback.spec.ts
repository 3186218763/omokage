import { test, expect, type Page } from "@playwright/test";

function wav(seconds = .65): string {
  const rate = 16000, count = Math.floor(rate * seconds);
  const data = Buffer.alloc(44 + count * 2);
  data.write("RIFF"); data.writeUInt32LE(data.length - 8, 4); data.write("WAVEfmt ", 8);
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22);
  data.writeUInt32LE(rate, 24); data.writeUInt32LE(rate * 2, 28); data.writeUInt16LE(2, 32);
  data.writeUInt16LE(16, 34); data.write("data", 36); data.writeUInt32LE(count * 2, 40);
  for (let i = 0; i < count; i++) data.writeInt16LE(Math.round(2000 * Math.sin(i / rate * 440 * Math.PI * 2)), 44 + i * 2);
  return data.toString("base64");
}
async function fixture(page: Page, seconds = .65, motions: [string, string] = ["点头", "摇头"]) {
  await page.route("**/healthz", route => route.fulfill({ json: { llm_configured: true, tts_available: true, asr_available: false } }));
  await page.route("**/api/live2d", route => route.fulfill({ status: 404, json: { ready: false } }));
  await page.route("**/api/playback", route => route.fulfill({ json: { status: "ok" } }));
  await page.route("**/api/interrupt", route => route.fulfill({ json: { status: "ok" } }));
  await page.route("**/api/chat", route => {
    const { turn_id } = route.request().postDataJSON();
    const events = [
      { type: "performance", revision: 0, emotion: "温柔", intensity: .9, confidence: 0, source: "speaking_style", decay_ms: 0 },
      { type: "sentence", index: 0, text: "第一句话。", motion: motions[0] },
      { type: "sentence", index: 1, text: "第二句话。", motion: motions[1] },
      { type: "audio", index: 0, audio: wav(seconds) },
      { type: "audio", index: 1, audio: wav(seconds) },
      { type: "performance", revision: 1, emotion: "俏皮", intensity: .6, confidence: .8, source: "kev", decay_ms: 0 },
      { type: "done", sentence_count: 2 },
    ];
    return route.fulfill({ contentType: "text/event-stream", body: events.map(e => `data: ${JSON.stringify({ ...e, v: 2, turn_id })}\n\n`).join("") });
  });
  await page.goto("/");
  await page.getByRole("textbox", { name: "消息" }).fill("你好");
  await page.getByRole("button", { name: "发送", exact: true }).click();
}
async function samples(page: Page) {
  return page.evaluate(() => (window as unknown as { omokagePlaybackSamples: () => { event: string; index?: number; ms: number; turn_id: string }[] }).omokagePlaybackSamples());
}
test("actual browser plays both queued clips after SSE done and synchronizes two motions", async ({ page }) => {
  await fixture(page);
  await expect.poll(async () => (await samples(page)).filter(s => s.event === "ended").length).toBe(2);
  const log = await samples(page);
  expect(log.filter(s => s.event === "playing").map(s => s.index)).toEqual([0, 1]);
  expect(log.filter(s => s.event === "motion_start").map(s => s.index)).toEqual([0, 1]);
  expect(log.find(s => s.event === "received_done")!.ms).toBeLessThan(log.find(s => s.event === "ended")!.ms);
});
test("repeats a head shake in the same reply at each sentence start", async ({ page }) => {
  await fixture(page, .65, ["摇头", "摇头"]);
  await expect.poll(async () => (await samples(page)).filter(s => s.event === "ended").length).toBe(2);
  const log = await samples(page);
  const starts = log.filter(s => s.event === "motion_start");
  expect(starts.map(s => s.index)).toEqual([0, 1]);
  for (const start of starts) {
    const playing = log.find(s => s.event === "playing" && s.index === start.index);
    expect(playing).toBeDefined();
    expect(start.ms).toBeGreaterThanOrEqual(playing!.ms);
  }
});
test("rejected playback produces no motion; a user retry starts it", async ({ page }) => {
  await page.addInitScript(() => {
    const play = HTMLMediaElement.prototype.play;
    let reject = true;
    HTMLMediaElement.prototype.play = function () {
      if (reject) { reject = false; return Promise.reject(new DOMException("blocked", "NotAllowedError")); }
      return play.call(this);
    };
  });
  await fixture(page);
  await expect.poll(async () => (await samples(page)).some(s => s.event === "received_done")).toBe(true);
  expect((await samples(page)).filter(s => s.event === "motion_start")).toHaveLength(0);
  await page.getByRole("button", { name: "记录", exact: true }).click();
  await page.getByRole("button", { name: "播放" }).first().click();
  await expect.poll(async () => (await samples(page)).filter(s => s.event === "motion_start").length).toBeGreaterThan(0);
});
test("starting a new turn stops the old audio queue and sends exact started indices", async ({ page }) => {
  await fixture(page, 2);
  await expect.poll(async () => (await samples(page)).filter(s => s.event === "playing").length).toBe(1);
  const oldTurn = (await samples(page)).find(s => s.event === "playing")!.turn_id;
  const interruptRequest = page.waitForRequest("**/api/interrupt");
  await page.getByRole("textbox", { name: "消息" }).fill("换个话题");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  expect((await interruptRequest).postDataJSON()).toMatchObject({ turn_id: oldTurn, started_indices: [0] });
  await expect.poll(async () => (await samples(page)).filter(s => s.event === "playing").length).toBe(2);
  expect((await samples(page)).filter(s => s.event === "playing" && s.turn_id === oldTurn).map(s => s.index)).toEqual([0]);
});
