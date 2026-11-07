// ONLYOFFICE 阅读器（设计稿 03 D-13）：外部引擎 ONLYOFFICE Docs 的只读查看器，Word、Excel、PPT、PDF 原生显示。
// 引擎由用户自己安装运行；签名的配置由外壳从后端取（source.engine），本阅读器只加载引擎的 api.js 并创建查看器。
// 社区版在只读模式下没有可用的接口往文档里加批注，所以标注只在外壳的侧栏里列出，不画在文档上。
import { useEffect, useRef } from "react";
import type { ViewerProps } from "../../reader/contract";
import "./onlyoffice.css";

/* eslint-disable @typescript-eslint/no-explicit-any */

const scripts = new Map<string, Promise<void>>();

function loadScript(url: string): Promise<void> {
  let p = scripts.get(url);
  if (!p) {
    p = new Promise<void>((resolve, reject) => {
      const el = document.createElement("script");
      el.src = url;
      el.async = true;
      el.onload = () => resolve();
      el.onerror = () => {
        scripts.delete(url);
        el.remove();
        reject(new Error(`连不上 ONLYOFFICE（${new URL(url).origin}）：检查设置里的地址，以及引擎是否在运行`));
      };
      document.head.appendChild(el);
    });
    scripts.set(url, p);
  }
  return p;
}

let seq = 0;

export default function OnlyofficeViewer(props: ViewerProps) {
  const { source } = props;
  const host = useRef<HTMLDivElement>(null);
  const live = useRef(props);
  live.current = props;

  useEffect(() => {
    let cancelled = false;
    let editor: any = null;
    const id = `bw-onlyoffice-${++seq}`;
    (async () => {
      try {
        if (!source.engine) throw new Error("设置里还没有填写 ONLYOFFICE 的地址");
        const { api, config } = await source.engine("onlyoffice");
        await loadScript(api);
        if (cancelled || !host.current) return;
        const DocsAPI = (window as any).DocsAPI;
        if (!DocsAPI?.DocEditor) throw new Error("ONLYOFFICE 的 api.js 没有提供 DocsAPI");
        const target = document.createElement("div");
        target.id = id;
        host.current.replaceChildren(target);
        editor = new DocsAPI.DocEditor(id, {
          ...(config as object),
          events: {
            onAppReady: () => live.current.onReady({ scrollTo: () => undefined }),
            onError: (e: any) => live.current.onError?.(`ONLYOFFICE 报错：${e?.data?.errorDescription ?? e?.data?.errorCode ?? "未知错误"}`),
          },
        });
      } catch (e) {
        if (!cancelled) live.current.onError?.(String((e as Error)?.message ?? e));
      }
    })();
    return () => {
      cancelled = true;
      try {
        editor?.destroyEditor?.();
      } catch {
        // 引擎已经不在时忽略
      }
    };
  }, [source.id, source.engine]);

  return <div ref={host} className="bw-onlyoffice" />;
}
