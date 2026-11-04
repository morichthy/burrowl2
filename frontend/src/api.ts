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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function call<T = any>(name: string, args: Record<string, unknown> = {}): Promise<T> {
  const res = await fetch(`./api/ops/${name}`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-burrowl-token": token() },
    body: JSON.stringify(args),
  });
  const body = await res.json();
  if (!body.ok) throw new ApiError(body.code, body.message, body.details);
  return body.result as T;
}

export function streamAgent(runId: string, onLine: (line: string) => void, onEnd: () => void): () => void {
  const es = new EventSource(`./api/agent/${runId}/stream?token=${encodeURIComponent(token())}`);
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
