// 列表右侧的预览栏（条目列表、检索结果共用）：不离开列表就能看到全文、地位、依据和用到它的。
// 只显示 entry.get 给出的内容，不推导地位；打开、阅读、关系图都是去别的页面。
import { useEffect } from "react";
import { call } from "../api";
import { CopyEntryId, EntryName } from "../entryLabels";
import { JUDGMENT_KIND, LINK_REL } from "../labels";
import { openReader } from "../reader/open";
import { href } from "../router";
import { Icon } from "../shell/icons";
import { CURSOR_EVENT } from "../shell/shortcuts";
import { Stamp, layerOf } from "../shell/Stamp";
import { Coordinates, ErrorBox, Loading, ReferenceWarnings, Time, useLoad } from "../ui";

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

function LinkList({ links, field, empty }: { links: any[]; field: "dst_id" | "src_id"; empty: string }) {
  if (!links.length) return <p className="muted small-text">{empty}</p>;
  return (
    <ul className="preview-links">
      {links.slice(0, 8).map((l) => (
        <li key={l.id}>
          <a href={href("entry", l[field])} title={l[field]}>
            <Stamp layer={layerOf(l[field])} small />
            <span className="clip"><EntryName id={l[field]} /></span>
          </a>
          <span className="muted small-text">{LINK_REL[l.rel] ?? l.rel}</span>
          <ReferenceWarnings status={l.basis_status} />
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
              {entry?.entry_kind === "judgment" && <>{JUDGMENT_KIND[entry.kind] ?? entry.kind} · </>}
              {entry?.author_id ?? entry?.data?.captured_by ?? ""} · <Time value={entry?.created_at} />
            </p>
            <Coordinates c={data.coordinates} />
            {entry?.entry_kind !== "artifact" && (
              <section>
                <h3>依据 <span className="muted">{(data.links_out ?? []).length}</span></h3>
                <LinkList links={data.links_out ?? []} field="dst_id" empty="没有引用依据。" />
              </section>
            )}
            <section>
              <h3>用到它的 <span className="muted">{(data.links_in ?? []).length}</span></h3>
              <LinkList links={data.links_in ?? []} field="src_id" empty="还没有条目引用它。" />
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
