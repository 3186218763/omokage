import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 临时调试配置：后端起在 8100（8000 被 labelu 占用）。用完可删。
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8100",
      "/healthz": "http://127.0.0.1:8100",
      "/live2d": "http://127.0.0.1:8100",
      "/tts": "http://127.0.0.1:8100",
    },
  },
});
