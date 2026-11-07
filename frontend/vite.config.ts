import { cpSync, existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// PDF.js 显示 PDF 需要的 CMap（中日韩字体）、标准字体、图像解码器与 ICC 配置（设计稿 02 D-02）：
// 构建时复制到产物的 pdfjs/ 下，开发服务器直接从 node_modules 提供；不从网络加载，离线安装包也能显示。
const PDFJS_DIRS = ["cmaps", "standard_fonts", "wasm", "iccs"];
const PDFJS_ROOT = resolve(__dirname, "node_modules/pdfjs-dist");

function pdfjsAssets(): Plugin {
  let outDir = "";
  return {
    name: "burrowl-pdfjs-assets",
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    writeBundle() {
      for (const dir of PDFJS_DIRS) {
        const src = join(PDFJS_ROOT, dir);
        if (existsSync(src)) cpSync(src, join(outDir, "pdfjs", dir), { recursive: true });
      }
    },
    configureServer(server) {
      server.middlewares.use("/pdfjs", (req, res, next) => {
        const file = join(PDFJS_ROOT, decodeURIComponent((req.url ?? "").split("?")[0]));
        if (!file.startsWith(PDFJS_ROOT) || !existsSync(file)) return next();
        res.end(readFileSync(file));
      });
    },
  };
}

// 构建产物放进 Python 包，随包分发；使用端不需要 Node（沿用 burrowl）
export default defineConfig({
  plugins: [react(), pdfjsAssets()],
  base: "./",
  build: { outDir: "../src/burrowl/web", emptyOutDir: true },
  test: { environment: "jsdom", globals: true },
});
