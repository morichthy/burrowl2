"""F1 过程捕获：只追加的轻量过程日志（草图 §2）。

日志不进入默认检索；被判断引用或被明确标记时，才升级为正式条目（见 artifacts.promote）。
执行者、会话、先后顺序由系统记录；条件只记捕获时能自动获得的部分，事后不能补写（草图 §3）。
"""
from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.model import SOURCE_CLASSES

LONG_OUTPUT = 4000  # 超过这个长度的输出存为 blob，日志里只记指纹与开头


class CaptureService:
    def __init__(self, ws):
        self.ws = ws

    def log(self, actor: Actor, op: str, *, input: dict | None = None, output: str | None = None,
            conditions: dict | None = None, objects: list[str] | None = None,
            source_class: str = "local", inputs: list[str] | None = None,
            outputs: list[str] | None = None) -> dict:
        """记一条过程事件。source_class：操作与测量记 local（本地实证），对话消息记 inferred（推断）。
        inputs / outputs：这次操作用到的、产出的原件（已登记的 art_…），写成关系 consumed / produced
        （设计稿 07 D-08）。"""
        if source_class not in SOURCE_CLASSES:
            raise BurrowlError("INVALID_ARGUMENT", "source_class 取值不对", {"source_class": source_class})
        for ref in [*(inputs or []), *(outputs or [])]:
            if (self.ws.ledger.get(ref) or {}).get("entry_kind") != "artifact":
                raise BurrowlError("NOT_FOUND", "inputs / outputs 必须是已登记的原件 art_…", {"ref": ref})
        data: dict = {"input": input or {}, "conditions": conditions or {}, "source_class": source_class}
        if output is not None:
            if len(output) > LONG_OUTPUT:
                data["output_sha256"] = self.ws.blobs.put(output.encode("utf-8"))
                data["output_head"] = output[:LONG_OUTPUT]
                data["output_truncated_in_log"] = True
            else:
                data["output"] = output
        objects = self.ws.linking.normalize_objects(objects or [])
        event = self.ws.ledger.insert("events", "evt", {
            "session_id": actor.session_id, "seq": self.ws.ledger.next_seq(actor.session_id),
            "actor_id": actor.id, "actor_kind": actor.kind, "op": op, "data": data,
        }, objects=objects)
        if objects and op != "constraints.check":
            self.ws.retrieval.flag_unchecked_constraints(actor, event)
        if inputs or outputs:
            self.attach(actor, event["id"], inputs=inputs, outputs=outputs)
        return event

    def attach(self, actor: Actor, event_id: str, *, inputs: list[str] | None = None,
               outputs: list[str] | None = None) -> None:
        """把原件连到一条过程日志上：consumed（用到）、produced（产出）。已有的同一关系不重复写。"""
        have = {(lk["rel"], lk["dst_id"]) for lk in self.ws.ledger.links_from(event_id)}
        for rel, refs in (("consumed", inputs or []), ("produced", outputs or [])):
            for ref in dict.fromkeys(refs):
                if (rel, ref) not in have:
                    self.ws.ledger.link(rel, event_id, ref, actor.id)

    def run_files(self, event_id: str) -> dict:
        """一条过程日志的输入与产出原件。"""
        out: dict[str, list[str]] = {"inputs": [], "outputs": []}
        for lk in self.ws.ledger.links_from(event_id):
            if lk["rel"] == "consumed":
                out["inputs"].append(lk["dst_id"])
            elif lk["rel"] == "produced":
                out["outputs"].append(lk["dst_id"])
        return out

    def output_of(self, event: dict) -> str:
        data = event["data"]
        if "output_sha256" in data:
            return self.ws.blobs.get(data["output_sha256"]).decode("utf-8")
        return data.get("output", "")

    def session(self, session_id: str) -> list[dict]:
        return self.ws.ledger.query("SELECT * FROM events WHERE session_id = ? ORDER BY seq", (session_id,))
