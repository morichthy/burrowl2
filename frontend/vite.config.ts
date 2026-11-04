import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 构建产物放进 Python 包，随包分发；使用端不需要 Node（沿用 burrowl）
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "../src/burrowl/web", emptyOutDir: true },
  test: { environment: "jsdom", globals: true },
});
