// Optional real-provider smoke, outside the deterministic test suite.
import { chromium } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
const base = process.env.OMOKAGE_URL ?? 'http://127.0.0.1:8011';
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  args: ['--autoplay-policy=no-user-gesture-required', '--enable-unsafe-swiftshader'] });
const page = await browser.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
  await page.goto(base);
  await page.getByRole('textbox', { name: '消息' }).fill('今天有点累，可以温柔地陪我聊两句吗？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.waitForFunction(() => window.omokagePlaybackSamples?.().some(e => e.event === 'ended'), null, { timeout: 90000 });
  await page.waitForFunction(() => window.omokagePlaybackSamples?.().some(e => e.event === 'received_done'), null, { timeout: 90000 });
  await page.waitForFunction(() => { const s = window.omokagePlaybackSamples?.() ?? []; return s.filter(e => e.event === 'ended').length === s.filter(e => e.event === 'received_audio').length; }, null, { timeout: 90000 });
  const samples = await page.evaluate(() => window.omokagePlaybackSamples());
  await writeFile('../docs/evaluation/live-smoke-2026-09-23.json', JSON.stringify({ base, errors, samples }, null, 2) + '\n');
  console.log(JSON.stringify({ errors, events: samples.map(e => e.event) }));
} finally { await browser.close(); }
