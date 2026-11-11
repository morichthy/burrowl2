// 线条图标（24×24，描边继承文字颜色）。只为辨识，不承载信息：每个图标旁边都有文字或 title。
// 全部内联在代码里，不从网络加载。

const PATHS: Record<string, string> = {
  // 导航
  home: "M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  search: "M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14zM20 20l-4-4",
  entries: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
  graph: "M6 6m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M18 8m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M10 18m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M8.3 7l7.3.7M7 8.3l2 7.4M16.3 9.8l-4.6 6.4",
  agent: "M4 5h16v11H8l-4 4zM8 9h8M8 12h5",
  decisions: "M9 12l2 2 4-4M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6z",
  pages: "M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7",
  record: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
  databases: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  coverage: "M3 3h4v4H3zM10 3h4v4h-4zM17 3h4v4h-4zM3 10h4v4H3zM10 10h4v4h-4zM17 10h4v4h-4zM3 17h4v4H3zM10 17h4v4h-4zM17 17h4v4h-4z",
  settings: "M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6zM12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1L7 17M17 7l2.1-2.1",
  // 界面
  back: "M15 5l-7 7 7 7",
  chevron: "M9 6l6 6-6 6",
  sidebar: "M4 5h16v14H4zM9 5v14",
  sun: "M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M20 14.5A8.5 8.5 0 0 1 9.5 4a7 7 0 1 0 10.5 10.5z",
  auto: "M4 5h16v11H4zM9 20h6M12 16v4",
  keyboard: "M3 7h18v10H3zM7 11h.01M11 11h.01M15 11h.01M8 14h8",
  plus: "M12 5v14M5 12h14",
  copy: "M9 9h11v11H9zM5 15V4h11",
  read: "M4 5c3-1 6-1 8 1 2-2 5-2 8-1v13c-3-1-6-1-8 1-2-2-5-2-8-1zM12 6v13",
  open: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  filter: "M4 5h16l-6 8v6l-4-2v-4z",
  bolt: "M13 3L5 14h6l-1 7 8-11h-6z",
  clock: "M12 4a8 8 0 1 1 0 16 8 8 0 0 1 0-16zM12 8v4l3 2",
  check: "M5 12l5 5 9-10",
  alert: "M12 4l9 16H3zM12 10v4M12 17v.01",
  info: "M12 4a8 8 0 1 1 0 16 8 8 0 0 1 0-16zM12 11v5M12 8v.01",
  close: "M6 6l12 12M18 6L6 18",
  target: "M12 4a8 8 0 1 1 0 16 8 8 0 0 1 0-16zM12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z",
  route: "M6 18a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 16h5a3 3 0 0 0 3-3v-3",
  hide: "M3 3l18 18M10.6 6.2A9.7 9.7 0 0 1 12 6c5 0 8.5 4 9.5 6-.4.8-1.2 2-2.5 3.200M6.300 7.800C4.300 9.100 3.000 10.900 2.500 12c1 2 4.500 6 9.500 6 1.200 0 2.300-.200 3.300-.600",
  fit: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  expand: "M4 10V4h6M20 14v6h-6M4 4l7 7M20 20l-7-7",
  layout: "M12 3v6M12 9l-7 6M12 9l7 6M5 15v3M19 15v3M12 15v3",
  inbox: "M4 13l2.500-8h11L20 13v6H4zM4 13h5l1 2.500h4L15 13h5",
};

export function Icon({ name, size }: { name: string; size?: number }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" style={size ? { width: size, height: size } : undefined}>
      <path d={PATHS[name] ?? ""} />
    </svg>
  );
}

// 标志：夜空里的一只猫头鹰（burrow + owl）。两只眼睛是原件绿与判断蓝，喙是框架橙
export function Owl() {
  return (
    <span className="logo" aria-hidden="true">
      <svg viewBox="0 0 32 32">
        <path d="M6 7l4 4.2A10 10 0 0 1 16 9a10 10 0 0 1 6 2.2L26 7l-.6 7.4A10.500 10.500 0 0 1 27 20c0 5.500-5 9-11 9S5 25.500 5 20c0-2 .5-3.900 1.600-5.600z" fill="#e8e6ff" opacity="0.14" />
        <circle cx="11.6" cy="17.2" r="4.3" fill="#2f9e6f" />
        <circle cx="20.4" cy="17.2" r="4.3" fill="#3b6fd8" />
        <circle cx="11.6" cy="17.2" r="1.7" fill="#0d1124" />
        <circle cx="20.4" cy="17.2" r="1.7" fill="#0d1124" />
        <circle cx="12.3" cy="16.4" r="0.6" fill="#fff" />
        <circle cx="21.1" cy="16.4" r="0.6" fill="#fff" />
        <path d="M14.6 21.6L16 24l1.4-2.400z" fill="#d98a2b" />
      </svg>
    </span>
  );
}
