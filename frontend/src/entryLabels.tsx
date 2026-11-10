import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { call } from "./api";

const REFERENCE = /^([a-z]+_)[0-9A-HJKMNP-TV-Z]{26}(?:@\d+)?(?:#[\w-]+)?$/;
const BATCH_SIZE = 200;
type Names = Record<string, string | null>;
const NameContext = createContext<{ names: Names; request: (ref: string) => void } | null>(null);

// 同一屏挂载的链接合并读取。离开此页面或刷新后重新取名，名称不落盘。
export function EntryLabels({ children }: { children: ReactNode }) {
  const [names, setNames] = useState<Names>({});
  const pending = useRef(new Set<string>());
  const requested = useRef(new Set<string>());
  const scheduled = useRef(false);
  const request = useCallback((ref: string) => {
    if (requested.current.has(ref)) return;
    requested.current.add(ref);
    pending.current.add(ref);
    if (scheduled.current) return;
    scheduled.current = true;
    queueMicrotask(() => {
      const refs = [...pending.current];
      pending.current.clear();
      scheduled.current = false;
      for (let offset = 0; offset < refs.length; offset += BATCH_SIZE) {
        const batch = refs.slice(offset, offset + BATCH_SIZE);
        call<Names>("entry.labels", { refs: batch }).then(
          (result) => setNames((before) => ({ ...before, ...result })),
          // 读取失败时仍可打开原链接；空值只用于后端确认的不可用条目。
          () => setNames((before) => ({ ...before, ...Object.fromEntries(batch.map((id) => [id, id])) })),
        );
      }
    });
  }, []);
  return <NameContext.Provider value={{ names, request }}>{children}</NameContext.Provider>;
}

export function EntryName({ id, name }: { id: string; name?: string }) {
  const context = useContext(NameContext);
  const request = context?.request;
  const prefix = REFERENCE.exec(id)?.[1];
  useEffect(() => {
    if (prefix && !name) request?.(id);
  }, [id, name, prefix, request]);
  if (!prefix) return <>{name || id}</>;
  const found = name || context?.names[id];
  if (found === id || (!context && !name)) return <span className="mono">{id}</span>;
  return (
    <span className="entry-name">
      <span className="entry-prefix mono">{prefix}</span>{" "}
      {found ?? (found === null ? `条目不可用 · ${id.split(/[&#@]/)[0].slice(-6)}` : "…")}
    </span>
  );
}

export function CopyEntryId({ id }: { id: string }) {
  const [message, setMessage] = useState("");
  return (
    <span className="small-text">
      <button type="button" className="link" title={id} onClick={async () => {
        try {
          await navigator.clipboard.writeText(id);
          setMessage("已复制");
        } catch {
          setMessage(id);
        }
      }}>复制 ID</button>
      {message && <span role="status"> {message}</span>}
    </span>
  );
}
