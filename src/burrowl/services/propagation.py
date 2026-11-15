"""F6 变化传播：只在框架层发生，只降不升（草图 §11.4）。

框架条目生成时记下输入清单（指向不可变单元及其版本）。有新判断、更正、撤回、新版本时：
1. 找出以这些条目为输入、或主题对象相同的框架条目，标为"输入已变化"；
2. 沿框架条目之间的派生关系继续传递，最多 max_depth 跳、max_items 个（DESIGN §0，参考 gbrain）；
3. 超出上限的部分标为"未核查"，并生成一条待决策项。
依据被加强时不自动提升下游；已被替代的条目不改回。
要点（设计稿 15 D-34）的来源是固定的原件段落：只有它引用的原件本身变化（新版本、退役、替换、删除，调用方用
changed_artifacts 说明）时才标为"输入已变化"；别人写了引用同一份原件的判断，不影响要点。
"""
DOWNGRADE_ORDER = {"valid": 0, "inputs_changed": 1, "unchecked": 2, "superseded": 3}


class Propagation:
    def __init__(self, ws):
        self.ws = ws

    def propagate(self, input_ids: list[str], *, objects: list[str] | None = None, reason: str = "",
                  changed_artifacts: list[str] | None = None) -> list[str]:
        fw = self.ws.framework
        cfg = self.ws.config["propagation"]
        changed = set(changed_artifacts or ())
        bases = [i.split("@", 1)[0].split("#", 1)[0] for i in input_ids if i]
        frontier = {(k, i) for k, i in fw.dependents([*input_ids, *bases, *changed])
                    if not self._point_untouched(k, i, changed)}
        for obj in objects or []:
            for page in fw.conn.execute("SELECT id FROM pages WHERE subject_id = ?", (obj,)):
                frontier.add(("page", page[0]))
        marked: list[str] = []
        seen: set[tuple[str, str]] = set()
        depth = 0
        while frontier and depth < cfg["max_depth"]:
            nxt: set[tuple[str, str]] = set()
            for kind, item_id in sorted(frontier):
                if (kind, item_id) in seen:
                    continue
                seen.add((kind, item_id))
                if len(marked) >= cfg["max_items"]:
                    break
                if self._downgrade(kind, item_id, "inputs_changed", reason):
                    marked.append(item_id)
                refs = [item_id]
                if kind == "page":
                    head = fw.page(item_id)["head_version"]
                    refs.append(f"{item_id}@{head}")
                nxt.update(fw.dependents(refs))
            frontier = nxt - seen
            depth += 1
        overflow = sorted(i for _, i in frontier - seen)
        if overflow:
            for kind, item_id in frontier - seen:
                self._downgrade(kind, item_id, "unchecked", reason)
            fw.add_decision("propagation_overflow", None, len(overflow),
                            {"reason": reason, "unchecked": overflow[:200], "limit": cfg})
        return marked

    def mark_pages(self, page_ids: list[str], *, reason: str) -> list[str]:
        """直接把这些页面标为"输入已变化"，再沿派生关系传给依赖它们的框架条目
        （抽取变化影响要点时用，设计稿 16 D-09）。"""
        marked = [pid for pid in page_ids if self._downgrade("page", pid, "inputs_changed", reason)]
        heads = [f"{pid}@{self.ws.framework.page(pid)['head_version']}" for pid in page_ids]
        return marked + self.propagate([*page_ids, *heads], reason=reason)

    def _point_untouched(self, kind: str, item_id: str, changed: set[str]) -> bool:
        """要点只随它引用的原件本身变化（D-34）。"""
        if kind != "page":
            return False
        fw = self.ws.framework
        page = fw.page(item_id)
        if page is None or page["type"] != "point":
            return False
        sources = {i.split("@", 1)[0].split("#", 1)[0] for i in fw.inputs_of("page", item_id, page["head_version"])}
        return not (sources & changed)

    def _downgrade(self, kind: str, item_id: str, state: str, reason: str) -> bool:
        fw = self.ws.framework
        item = fw.page(item_id) if kind == "page" else fw.edge(item_id)
        if item is None or DOWNGRADE_ORDER[item["freshness"]] >= DOWNGRADE_ORDER[state]:
            return False
        fw.set_state(kind, item_id, freshness=state)
        if kind == "page" and not fw.open_decision_for("rederive", item_id):
            fw.add_decision("rederive", item_id, 1, {"reason": reason, "title": item["title"]})
        return True
