import { EntryLabels } from "./entryLabels";
import { Agent } from "./pages/Agent";
import { Coverage } from "./pages/Coverage";
import { Databases } from "./pages/Databases";
import { Decisions } from "./pages/Decisions";
import { Entries, Entry } from "./pages/Entries";
import { Graph } from "./pages/Graph";
import { Home } from "./pages/Home";
import { Pages } from "./pages/Pages";
import { Reading } from "./pages/Reading";
import { Record } from "./pages/Record";
import { Reader } from "./reader/Reader";
import { Search } from "./pages/Search";
import { Settings } from "./pages/Settings";
import { useRoute } from "./router";
import { Shell } from "./shell/Shell";
import { Toasts } from "./shell/toast";

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
      return <Agent key={a} runId={a} />;
    case "databases":
      return <Databases />;
    case "settings":
      return <Settings />;
    case "decisions":
      return <Decisions />;
    case "pages":
      return <Pages />;
    case "coverage":
      return <Coverage key={a} artifactId={a} />;
    case "reading":
      return <Reading key={a} sessionId={a} />;
    case "record":
      return <Record key={a} versionOf={a} />;
    default:
      return <Home />;
  }
}

export default function App() {
  const route = useRoute();
  // 阅读模式（设计稿 03 D-01）：只有阅读器本身，不显示导航
  if (route[0] === "read") return (
    <>
      <EntryLabels key={route[1]}><Reader target={route[1] ?? ""} /></EntryLabels>
      <Toasts />
    </>
  );
  return (
    <>
      <Shell route={route}>
        <Page route={route} />
      </Shell>
      <Toasts />
    </>
  );
}

