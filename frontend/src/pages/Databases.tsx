// 数据目录：一个工作台管理多个数据目录，其中一个是默认（D-18）。
// 默认目录：工作台网址不带 ?db= 时打开它；不带 --data 登记的 MCP 与命令行也连接它。
// 移除只是取消登记，目录里的数据不动，之后可以重新登记。
import { useEffect, useState } from "react";
import { call, pinDb, switchDb } from "../api";
import { Action, ErrorBox, Panel, Tag, useLoad } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function Databases() {
  const [list, error, reload] = useLoad(() => call<any>("workspace.list"), []);
  const [form, setForm] = useState({ path: "", name: "", make_default: false, create: false });
  const items: any[] = list?.items ?? [];
  return (
    <div className="forms single">
      <Panel title="数据目录">
        <p className="muted">
          每个数据目录有自己独立的账本、框架和索引，记录不会跨目录。侧栏顶部可以随时切换；不带 <code>--data</code> 登记的 MCP 跟着默认目录走，在这里改了默认，AI 的下一次调用就连到新的默认目录。
        </p>
        <ErrorBox error={error} />
        <table className="db-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>路径</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((w) => (
              <tr key={w.path}>
                <td>
                  <strong>{w.name}</strong> {w.default && <Tag tone="accent">默认</Tag>} {w.name === list?.current && <Tag>当前</Tag>}{" "}
                  {!w.exists && <Tag tone="bad">目录不存在</Tag>}
                </td>
                <td>
                  <code className="data-path">{w.path}</code>
                </td>
                <td className="service-buttons">
                  {w.name !== list?.current && w.exists && (
                    <button type="button" className="small" onClick={() => switchDb(w.name)}>
                      打开
                    </button>
                  )}
                  {!w.default && (
                    <Action
                      label="设为默认"
                      className="small"
                      run={async () => {
                        await call("workspace.set_default", { name: w.name });
                        reload();
                      }}
                    />
                  )}
                  {!w.default && (
                    <Action
                      label="移除登记"
                      className="small danger"
                      run={async () => {
                        if (!window.confirm(`从列表移除“${w.name}”？目录里的数据不会被删除，之后可以重新登记。`)) return;
                        await call("workspace.remove", { name: w.name });
                        if (w.name === list?.current) switchDb(null, "#/databases");
                        else reload();
                      }}
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title="登记数据目录">
        <p className="muted">填已有数据目录的路径即可登记；目录里还没有数据时，勾选“新建”才会建立新的数据目录。旧版 burrowl 的数据目录不能直接登记，需要新建后导入。</p>
        <input value={form.path} onChange={(e) => setForm({ ...form, path: e.target.value })} placeholder="绝对路径，例如 D:\BurrowlData2\project-b" />
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="名称（可选，默认取目录名；用在网址 ?db= 里）" />
        <label className="check">
          <input type="checkbox" checked={form.create} onChange={(e) => setForm({ ...form, create: e.target.checked })} /> 目录里没有数据时新建
        </label>
        <label className="check">
          <input type="checkbox" checked={form.make_default} onChange={(e) => setForm({ ...form, make_default: e.target.checked })} /> 设为默认
        </label>
        <Action
          label="登记"
          className="primary"
          disabled={!form.path.trim()}
          run={async () => {
            await call("workspace.add", { path: form.path.trim(), name: form.name.trim() || null, make_default: form.make_default, create: form.create });
            setForm({ path: "", name: "", make_default: false, create: false });
            reload();
          }}
        />
      </Panel>
    </div>
  );
}

// 侧栏顶部的切换器：列出登记的数据目录，选中即切换（整页重新加载）
export function DbSwitcher() {
  const [list, error] = useLoad(() => call<any>("workspace.list"), []);
  useEffect(() => {
    if (list?.current) pinDb(list.current);
  }, [list]);
  if (error) {
    return (
      <div className="db-switch error-text" title={error}>
        数据目录不可用 · <button type="button" className="link" onClick={() => switchDb(null)}>打开默认</button>
      </div>
    );
  }
  const items: any[] = list?.items ?? [];
  return (
    <label className="db-switch" title={list?.current_path ?? ""}>
      <span className="nav-title">数据目录</span>
      <select
        value={list?.current ?? ""}
        onChange={(e) => {
          const w = items.find((i) => i.name === e.target.value);
          if (w) switchDb(w.name);
        }}
      >
        {items.map((w) => (
          <option key={w.path} value={w.name} disabled={!w.exists}>
            {w.name}
            {w.default ? "（默认）" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
