// 工作台调用后端的唯一入口：POST /api/ops/{name}。token 来自网址 ?token=，保存在 sessionStorage。

const KEY = "burrowl-token";

export function token(): string {
  const fromUrl = new URLSearchParams(window.location.search).get("token");
  if (fromUrl) {
    sessionStorage.setItem(KEY, fromUrl);
    return fromUrl;
  }
  return sessionStorage.getItem(KEY) ?? "";
}

export class ApiError extends Error {
  constructor(public code: string, message: string, public details: unknown) {
    super(message);
  }
}

// 当前数据目录：网址 ?db=名称（D-18）。放在网址里，两个标签页可以各开一个目录。
export function currentDb(): string {
  return new URLSearchParams(window.location.search).get("db") ?? "";
}

// 打开时网址里没有 db（用的是默认目录）：把它写进网址但不重新加载。
// 这样别处改了默认目录，这个标签页也不会悄悄换到另一个目录。
export function pinDb(name: string): void {
  if (!name || currentDb()) return;
  const params = new URLSearchParams(window.location.search);
  params.set("db", name);
  window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
}

// 切换数据目录：换掉网址里的 db 并整页重新加载，避免上一个目录的数据留在页面状态里。name 为空时回到默认目录
export function switchDb(name: string | null, page = "#/"): void {
  const params = new URLSearchParams(window.location.search);
  params.set("token", token());
  if (name) params.set("db", name);
  else params.delete("db");
  window.location.assign(`${window.location.pathname}?${params.toString()}${page}`);
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function call<T = any>(name: string, args: Record<string, unknown> = {}): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json", "x-burrowl-token": token() };
  const db = currentDb();
  if (db) headers["x-burrowl-data"] = db;
  const res = await fetch(`./api/ops/${name}`, {
    method: "POST",
    headers,
    body: JSON.stringify(args),
  });
  const body = await res.json();
  if (!body.ok) throw new ApiError(body.code, body.message, body.details);
  return body.result as T;
}

export function streamAgent(runId: string, onLine: (line: string) => void, onEnd: () => void): () => void {
  const db = currentDb();
  const es = new EventSource(`./api/agent/${runId}/stream?token=${encodeURIComponent(token())}${db ? `&db=${encodeURIComponent(db)}` : ""}`);
  es.onmessage = (e) => onLine(JSON.parse(e.data).line);
  es.addEventListener("end", () => {
    es.close();
    onEnd();
  });
  es.onerror = () => {
    es.close();
    onEnd();
  };
  return () => es.close();
}

// 原件文件、页面图像、嵌入图片的地址（设计稿 01 D-07）。<img>、<video>、<iframe> 不能带请求头，token 和 db 放在网址里
function fileQuery(extra: Record<string, string> = {}): string {
  const params = new URLSearchParams({ token: token(), ...extra });
  const db = currentDb();
  if (db) params.set("db", db);
  return params.toString();
}

export function fileUrl(artifactId: string, download = false): string {
  return `./api/artifact/${artifactId}/file?${fileQuery(download ? { download: "true" } : {})}`;
}

// 页面内读取原件字节（PDF.js、docx-preview）：走 /bytes，不走 /file。
// IDM、FDM 等下载管理器的扩展会拦截 application/pdf、Word 的响应（页面拿到 204 并弹出下载框），/bytes 不会被当成文件下载。
// token 和 db 放在请求头里，不进网址。
export async function fetchArtifactBytes(artifactId: string, what: "bytes" | "snapshot/bytes" = "bytes"): Promise<ArrayBuffer> {
  const headers: Record<string, string> = { "x-burrowl-token": token() };
  const db = currentDb();
  if (db) headers["x-burrowl-data"] = db;
  const res = await fetch(`./api/artifact/${artifactId}/${what}`, { headers });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.code ?? "HTTP_ERROR", body?.message ?? `原件读取失败（${res.status}）`, body?.details);
  }
  return res.arrayBuffer();
}

// clip：只要页面上的一块（块的 box，占页面的比例），用于公式等的裁切图（设计稿 03 D-16）
// 外部阅读引擎（设计稿 03 D-13）的签名配置：{api, config}
export async function fetchEngineConfig(artifactId: string, engine: string): Promise<{ api: string; config: unknown }> {
  const headers: Record<string, string> = { "x-burrowl-token": token() };
  const db = currentDb();
  if (db) headers["x-burrowl-data"] = db;
  const res = await fetch(`./api/artifact/${artifactId}/engine/${engine}`, { headers });
  const body = await res.json();
  if (!res.ok || body.ok === false) throw new ApiError(body?.code ?? "HTTP_ERROR", body?.message ?? `取引擎配置失败（${res.status}）`, body?.details);
  return body;
}

export function pageUrl(artifactId: string, page: number, scale = 1.5, source = "auto", clip?: number[]): string {
  return `./api/artifact/${artifactId}/page/${page}.png?${fileQuery({ scale: String(scale), source, ...(clip ? { clip: clip.join(",") } : {}) })}`;
}

export function blobUrl(artifactId: string, sha: string, mime = "image/png"): string {
  return `./api/artifact/${artifactId}/blob/${sha}?${fileQuery({ mime })}`;
}
