import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./browser-tests", workers: 1,
  use: { baseURL: "http://127.0.0.1:4175", launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ["--autoplay-policy=no-user-gesture-required"],
  } },
  webServer: { command: "npm run dev -- --host 127.0.0.1 --port 4175 --strictPort", url: "http://127.0.0.1:4175", reuseExistingServer: false },
});
