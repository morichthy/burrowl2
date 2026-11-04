"""F6 变化传播：只在框架层发生，只降不升（草图 §11.4）。

框架条目生成时记下输入清单（指向不可变单元及其版本）。有新判断、更正、撤回、新版本时：
1. 找出以这些条目为输入、或主题对象相同的框架条目，标为"输入已变化"；
2. 沿框架条目之间的派生关系继续传递，最多 max_depth 跳、max_items 个（DESIGN §0，参考 gbrain）；
3. 超出上限的部分标为"未核查"，并生成一条待决策项。
依据被加强时不自动提升下游；已被替代的条目不改回。
"""
DOWNGRADE_ORDER = {"valid": 0, "inputs_changed": 1, "unchecked": 2, "superseded": 3}


class Propagation:
    def __init__(self, ws):
        self.ws = ws

    def propagate(self, input_ids: list[str], *, objects: list[str] | None = None, reason: str = "") -> list[str]:
        fw = self.ws.framework
        cfg = self.ws.config["propagation"]
        bases = [i.split("@", 1)[0].split("#", 1)[0] for i in input_ids if i]
        frontier = set(fw.dependents([*input_ids, *bases]))
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

    def _downgrade(self, kind: str, item_id: str, state: str, reason: str) -> bool:
        fw = self.ws.framework
        item = fw.page(item_id) if kind == "page" else fw.edge(item_id)
        if item is None or DOWNGRADE_ORDER[item["freshness"]] >= DOWNGRADE_ORDER[state]:
            return False
        fw.set_state(kind, item_id, freshness=state)
        if kind == "page" and not fw.open_decision_for("rederive", item_id):
            fw.add_decision("rederive", item_id, 1, {"reason": reason, "title": item["title"]})
        return True
