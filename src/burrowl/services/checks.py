"""原件检查：外部原件（referenced，只登记路径和指纹）在原位置是否还与登记时一致。

- 复制保存（managed）的原件按内容寻址存放，不会变，不检查。
- 每条版本链只查最新的一版：旧版本的文件被新版本覆盖是预期内的。
- 先比大小和修改时间，没变就算一致；变了才重算 sha256，大文件也能常查。
- 结果是"现在磁盘上的情况"，可以随时重算，所以存在数据目录的 checks.json，不写进账本。
  发现变化后系统不自动处理：由人或 agent 把新文件登记为新版本（version_of），走现有的传播。
"""
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from ..core.hashing import sha256_file

STATE_FILE = "checks.json"
DEFAULT_INTERVAL_HOURS = 6


class SourceCheck:
    def __init__(self, ws):
        self.ws = ws
        self._lock = threading.Lock()
        self._timer: threading.Thread | None = None

    @property
    def interval_hours(self) -> float:
        """定时检查间隔（小时）；config.json 的 artifact_check.interval_hours 设为 0 关闭。"""
        conf = self.ws.config.get("artifact_check") or {}
        return float(conf.get("interval_hours", DEFAULT_INTERVAL_HOURS))

    def _path(self) -> Path:
        return self.ws.root / STATE_FILE

    def _load(self) -> dict:
        try:
            return json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _targets(self) -> list[dict]:
        """每条版本链的最新一版外部原件。"""
        sql = ("SELECT id FROM artifacts a WHERE storage = 'referenced' "
               "AND NOT EXISTS (SELECT 1 FROM artifacts b WHERE b.version_of = a.id) ORDER BY created_at")
        return [self.ws.ledger.get(r["id"]) for r in self.ws.ledger.query(sql)]

    def run(self, *, trigger: str = "manual") -> dict:
        with self._lock:
            previous = self._load().get("files", {})
            files, problems = {}, []
            for art in self._targets():
                path = Path(art["data"].get("path", ""))
                entry = {"path": str(path), "title": art["data"].get("title")}
                if not path.is_file():
                    entry["status"] = "missing"
                else:
                    stat = path.stat()
                    entry.update(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                    known = previous.get(art["id"], {})
                    if stat.st_size != art["data"].get("size"):
                        entry["status"] = "changed"
                    elif known.get("status") == "ok" and known.get("mtime_ns") == stat.st_mtime_ns \
                            and known.get("size") == stat.st_size:
                        entry["status"] = "ok"  # 大小和修改时间都与上次核对过的一致，不重算指纹
                    else:
                        entry["status"] = "ok" if sha256_file(path) == art["sha256"] else "changed"
                files[art["id"]] = entry
                if entry["status"] != "ok":
                    problems.append({"artifact_id": art["id"], **entry})
            state = {"checked_at": datetime.now(UTC).isoformat(timespec="seconds"), "trigger": trigger,
                     "checked": len(files), "changed": sum(e["status"] == "changed" for e in files.values()),
                     "missing": sum(e["status"] == "missing" for e in files.values()), "files": files}
            tmp = self._path().with_suffix(".tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path())
        return {**self._summary(state), "problems": problems}

    def _summary(self, state: dict) -> dict:
        hours = self.interval_hours
        return {"checked_at": state.get("checked_at"), "trigger": state.get("trigger"),
                "checked": state.get("checked", 0), "changed": state.get("changed", 0),
                "missing": state.get("missing", 0),
                "schedule": {"enabled": hours > 0, "interval_hours": hours,
                             "running": bool(self._timer and self._timer.is_alive())}}

    def status(self) -> dict:
        """上次检查的结果（不重新检查），以及有问题的原件列表。"""
        state = self._load()
        problems = [{"artifact_id": k, **v} for k, v in state.get("files", {}).items() if v.get("status") != "ok"]
        return {**self._summary(state), "problems": problems,
                "referenced_total": len(self._targets())}

    def start_schedule(self) -> None:
        """工作台进程里的定时检查：启动后先查一次，之后按间隔查。间隔为 0 时不启动。"""
        if self.interval_hours <= 0 or (self._timer and self._timer.is_alive()):
            return

        def loop():
            time.sleep(5)  # 等服务先起来
            while self.interval_hours > 0:
                try:
                    self.run(trigger="schedule")
                except Exception:  # noqa: BLE001 —— 定时任务出错不能拖垮工作台；下次再查
                    pass
                time.sleep(self.interval_hours * 3600)

        self._timer = threading.Thread(target=loop, name="artifact-check", daemon=True)
        self._timer.start()
