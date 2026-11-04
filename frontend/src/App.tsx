import { useCallback } from "react";
import { call } from "./api";
import { Agent } from "./pages/Agent";
import { Decisions } from "./pages/Decisions";
import { Entries, Entry } from "./pages/Entries";
import { Graph } from "./pages/Graph";
import { Home } from "./pages/Home";
import { Pages } from "./pages/Pages";
import { Record } from "./pages/Record";
import { Search } from "./pages/Search";
import { href, useRoute } from "./router";
import { useLoad, usePoll } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

// 线条图标（24×24，描边继承文字颜色），只为导航辨识
const ICONS: Record<string, string> = {
  "": "M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  search: "M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14zM20 20l-4-4",
  entries: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
  graph: "M6 6m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M18 8m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M10 18m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M8.3 7l7.3.7M7 8.3l2 7.4M16.3 9.8l-4.6 6.4",
  agent: "M4 5h16v11H8l-4 4zM8 9h8M8 12h5",
  decisions: "M9 12l2 2 4-4M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6z",
  pages: "M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7",
  record: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
};

// 导航分组：工作 / 治理
const NAV: [string, string][][] = [
  [
    ["", "首页"],
    ["search", "检索"],
    ["entries", "条目"],
    ["graph", "关系图"],
    ["pages", "框架页"],
  ],
  [
    ["decisions", "待决策"],
    ["record", "人工记录"],
    ["agent", "Agent"],
  ],
];
const GROUP_TITLES = ["工作", "治理"];

function Icon({ name }: { name: string }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={ICONS[name] ?? ""} />
    </svg>
  );
}

function Page({ route }: { route: string[] }) {
  const [page, a] = route;
  switch (page) {
    case "search":
      return <Search />;
    case "entries":
      return <Entries />;
    case "entry":
      return <Entry key={a} id={a ?? ""} />;
    case "graph":
      return <Graph center={a} />;
    case "agent":
      return <Agent />;
    case "decisions":
      return <Decisions />;
    case "pages":
      return <Pages />;
    case "record":
      return <Record key={a} versionOf={a} />;
    default:
      return <Home />;
  }
}

export default function App() {
  const route = useRoute();
  const [stats, , reload] = useLoad(() => call<any>("stats.overview"), []);
  usePoll(useCallback(reload, [reload]), 8000);
  const decisions = Object.values((stats?.decisions ?? {}) as Record<string, number>).reduce((s, n) => s + n, 0);
  const badges: Record<string, number> = {
    decisions,
    pages: (stats?.pages?.freshness?.inputs_changed ?? 0) + (stats?.pages?.freshness?.unchecked ?? 0),
    agent: stats?.runs?.running ?? 0,
  };
  const current = route[0] === "entry" ? "entries" : (route[0] ?? "");
  return (
    <div className="app">
      <nav className="side">
        <a className="brand" href="#/">
          <span className="logo">b</span>
          <span>
            研发工作台
            <small>burrowl</small>
          </span>
        </a>
        {NAV.map((group, i) => (
          <div className="nav-group" key={i}>
            <div className="nav-title">{GROUP_TITLES[i]}</div>
            {group.map(([key, text]) => (
              <a key={key} href={key ? href(key) : "#/"} className={current === key ? "on" : ""} aria-current={current === key ? "page" : undefined}>
                <Icon name={key} />
                <span>{text}</span>
                {badges[key] ? <span className="badge-dot">{badges[key]}</span> : null}
              </a>
            ))}
          </div>
        ))}
      </nav>
      <main key={current}>
        <Page route={route} />
      </main>
    </div>
  );
}
