"""一个进程管理多个数据目录（D-18）：按登记表找到数据目录，按需打开它的 Workspace 并缓存。

- 工作台进程用它：每个请求按 ?db= 或请求头 x-burrowl-data 选数据目录，不带就是默认目录；
- 不带 --data 启动的 MCP 用它：每次调用都按登记表里当前的默认目录选，工作台改了默认，下一次调用就跟着变；
- 定时检查用它：轮流检查所有登记的数据目录；后台线程也在这里给各目录补建检索向量（设计稿 06 D-07）。
各数据目录的账本、配置、身份（human_id）互相独立；一个请求只作用于一个数据目录。
每次取 Workspace 都核对 config.json 的修改时间，被别的进程改过就重读（Workspace.refresh_config）。
"""
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from ..core.errors import BurrowlError
from ..services.workspace import Workspace
from . import install


class WorkspacePool:
    def __init__(self, pinned: Path | None = None):
        """pinned：固定只用这一个数据目录（mcp --data、serve 测试）；为空时跟着登记表。"""
        self.pinned = Path(pinned).resolve() if pinned else None
        self._open: dict[str, Workspace] = {}
        self._lock = threading.Lock()
        self._schedule: threading.Thread | None = None

    @classmethod
    def of(cls, target: "Workspace | WorkspacePool") -> "WorkspacePool":
        """已经打开的单个 Workspace 包成只连它的 pool（测试、agent 子进程）。"""
        if isinstance(target, WorkspacePool):
            return target
        pool = cls(target.root)
        pool._open[str(target.root)] = target
        return pool

    def get(self, root: Path) -> Workspace:
        key = str(Path(root).resolve())
        with self._lock:
            ws = self._open.get(key)
            if ws is None:
                ws = self._open[key] = Workspace(key)
                return ws
        # 别的进程（工作台、命令行）改了 config.json：下一次调用就用新设置（设计稿 06 D-21），不用重启 MCP 客户端
        ws.refresh_config()
        return ws

    def default_root(self) -> Path:
        if self.pinned:
            return self.pinned
        root = install.default_workspace()
        if root is None:
            raise BurrowlError("NO_DATA_DIR", "没有登记数据目录：先运行 burrowl init <目录>")
        return root

    def resolve(self, key: str | None = None) -> Workspace:
        """按名称（或路径）选数据目录；为空时用默认目录。固定了数据目录时只认它自己。"""
        if not key:
            return self.get(self.default_root())
        if self.pinned:
            if key in (install.name_of(self.pinned), str(self.pinned)):
                return self.get(self.pinned)
            raise BurrowlError("NOT_FOUND", f"这个进程只连接数据目录 {self.pinned}")
        return self.get(install.find_workspace(key))

    def roots(self) -> list[Path]:
        if self.pinned:
            return [self.pinned]
        return [Path(i["path"]) for i in install.workspaces() if i["exists"]]

    # ---------- 定时检查外部原件：覆盖所有登记的数据目录 ----------
    def run_due_checks(self, now: datetime | None = None) -> list[str]:
        """检查到期的数据目录（间隔按各自 config.json 的 artifact_check.interval_hours），返回检查过的目录。"""
        done = []
        for root in self.roots():
            try:
                ws = self.get(root)
                ws.source_check.scheduled = True
                if ws.source_check.due(now):
                    ws.source_check.run(trigger="schedule")
                    done.append(str(root))
            except Exception:  # noqa: BLE001 —— 一个目录打不开或检查出错，不影响其他目录和工作台
                continue
            try:  # 定期巡检到期：只在本机准备巡检包，不调用大模型（设计稿 08 D-01、D-03）
                with ws.lock:
                    ws.inspection.run_due(now)
            except Exception:  # noqa: BLE001 —— 准备巡检包出错不影响原件检查与工作台
                continue
        return done

    def start_schedule(self, tick_seconds: float = 60) -> None:
        if self._schedule and self._schedule.is_alive():
            return

        def loop():
            time.sleep(5)  # 等服务先起来
            while True:
                self.run_due_checks(datetime.now(UTC))
                time.sleep(tick_seconds)

        self._schedule = threading.Thread(target=loop, name="artifact-check", daemon=True)
        self._schedule.start()
        self._vectors = threading.Thread(target=self._vector_loop, name="vector-build", daemon=True)
        self._vectors.start()

    # ---------- 后台补建向量（设计稿 06 D-07）：只在工作台进程里运行 ----------
    def build_vectors_once(self, seconds: float = 30) -> int:
        """给每个登记的数据目录补一批向量（每个目录最多 seconds 秒），返回本轮补了多少个单元。"""
        built = 0
        for root in self.roots():
            try:
                built += self.get(root).vectors.build(seconds=seconds).get("built", 0)
            except Exception:  # noqa: BLE001 —— 一个目录出错（缺模型、库被占用）不影响其他目录和工作台
                continue
        return built

    def _vector_loop(self) -> None:
        time.sleep(10)
        while True:
            if not self.build_vectors_once():
                time.sleep(30)  # 没有要补的：隔一会儿再看（新登记的原件、新判断）
