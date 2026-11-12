// 列表右侧的预览栏（条目列表、检索结果共用）：不离开列表就能看到全文、坐标、本条指向与指向本条的关系。
// 只显示 entry.get 给出的内容，不推导地位；打开、阅读、关系图都是去别的页面。
import { useEffect } from "react";
import { call } from "../api";
import { CopyEntryId, EntryName } from "../entryLabels";
import { KIND, VALIDITY } from "../labels";
import { openReader } from "../reader/open";
import { href } from "../router";
import { Icon } from "../shell/icons";
import { CURSOR_EVENT } from "../shell/shortcuts";
import { Stamp, layerOf } from "../shell/Stamp";
import { Coordinates, ErrorBox, Loading, Tag, Time, useLoad } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

// 键盘光标移到哪一行，预览就跟到哪一行
export function useCursorPreview(onPick: (id: string) => void): void {
  useEffect(() => {
    const on = (e: Event) => {
      const id = (e as CustomEvent<string>).detail;
      if (id) onPick(id);
    };
    window.addEventListener(CURSOR_EVENT, on);
    return () => window.removeEventListener(CURSOR_EVENT, on);
  }, [onPick]);
}

function LinkList({ links, empty }: { links: any[]; empty: string }) {
  if (!links.length) return <p className="muted small-text">{empty}</p>;
  return (
    <ul className="preview-links">
      {links.slice(0, 8).map((l, i) => (
        <li key={`${l.id ?? l.other}:${i}`}>
          <a href={href("entry", l.other)} title={l.other}>
            <Stamp layer={layerOf(l.other)} small />
            <span className="clip">{l.other_label ?? <EntryName id={l.other} />}</span>
          </a>
          <span className="muted small-text">{l.phrase}</span>
          {l.other_validity && l.other_validity !== "current" && <Tag tone="warn">{VALIDITY[l.other_validity] ?? l.other_validity}</Tag>}
        </li>
      ))}
      {links.length > 8 && <li className="muted small-text">还有 {links.length - 8} 条，打开后查看</li>}
    </ul>
  );
}

export function EntryPreview({ id, onClose }: { id: string; onClose: () => void }) {
  const base = id.split("#")[0];
  const [data, error] = useLoad(() => call<any>("entry.get", { id }), [id]);
  const entry = data?.entry;
  const text: string = entry?.data?.text ?? entry?.data?.result ?? entry?.data?.title ?? entry?.data?.excerpt ?? "";
  const layer = data?.coordinates?.layer ?? layerOf(base);
  return (
    <aside className="preview" aria-label="预览">
      <header>
        <Stamp layer={layer} />
        <span className="mono muted clip grow">{id}</span>
        <CopyEntryId id={id} />
        <button type="button" className="icon-button" onClick={onClose} title="关闭预览" aria-label="关闭预览"><Icon name="close" size={16} /></button>
      </header>
      <div className="preview-body">
        <ErrorBox error={error} />
        {!data && !error && <Loading lines rows={5} />}
        {data && (
          <>
            <p className="preview-title"><EntryName id={id} /></p>
            {text && text !== entry?.data?.title && <p className="preview-text">{text.length > 600 ? `${text.slice(0, 600)}…` : text}</p>}
            <p className="muted small-text">
              {data.coordinates?.kind && <>{KIND[data.coordinates.kind] ?? data.coordinates.kind} · </>}
              {entry?.author_id ?? entry?.captured_by ?? entry?.actor_id ?? ""} · <Time value={entry?.created_at} />
            </p>
            <Coordinates c={data.coordinates} />
            {entry?.entry_kind !== "artifact" && (
              <section>
                <h3>本条指向 <span className="muted">{(data.relations?.out ?? []).length}</span></h3>
                <LinkList links={data.relations?.out ?? []} empty="没有依据，也没有其他关系。" />
              </section>
            )}
            <section>
              <h3>指向本条 <span className="muted">{(data.relations?.in ?? []).length}</span></h3>
              <LinkList links={data.relations?.in ?? []} empty="还没有条目指向它。" />
            </section>
          </>
        )}
      </div>
      <footer>
        <a className="button primary grow" href={href("entry", id)}>打开 <kbd>Enter</kbd></a>
        <button type="button" onClick={() => openReader(base, id.split("#")[1])}><Icon name="read" size={15} />阅读</button>
        <a className="button" href={href("graph", base)}><Icon name="graph" size={15} />关系图</a>
      </footer>
    </aside>
  );
}
