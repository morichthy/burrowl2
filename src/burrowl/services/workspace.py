"""组合根：按数据目录装配存储与各服务。

数据目录布局：
    ledger.sqlite      原件与判断（只追加，唯一不可替代的部分）
    framework.sqlite   框架层（可再生）
    index.sqlite       全文索引（可删除重建）
    blobs/             内容寻址的原件文件
    config.json        配置（agent 命令模板等）
"""
import json
from pathlib import Path

from .. import FORMAT_VERSION, __version__
from ..core.errors import BurrowlError
from ..index.fts import Index
from ..index.segment import SEGMENTER_VERSION
from ..store.blobs import BlobStore
from ..store.db import connect, get_meta, migrate, set_meta
from ..store.framework import Framework
from ..store.ledger import Ledger
from .agents import AgentService
from .artifacts import ArtifactService
from .capture import CaptureService
from .framework import FrameworkService
from .import_v1 import ImportV1
from .judgments import JudgmentService
from .linking import LinkingService
from .overview import OverviewService
from .portability import Portability
from .propagation import Propagation
from .retrieval import RetrievalService

DEFAULT_CONFIG = {
    # agent 命令模板：{prompt} 为任务文本，{mcp_config} 为本数据目录生成的 MCP 配置文件路径（DESIGN §3.3 第 6 步）
    "agents": {
        "claude": {"command": ["claude", "-p", "{prompt}", "--mcp-config", "{mcp_config}",
                               "--output-format", "text"]},
        "codex": {"command": ["codex", "exec", "{prompt}"]},
    },
    "human_id": "human:workbench",
    "propagation": {"max_depth": 8, "max_items": 1000},
    "linking": {"impact_threshold": 10},
}


class Workspace:
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        if (self.root / ".burrowl").is_dir() and not (self.root / "ledger.sqlite").exists():
            # 防止把旧版数据目录当成新版打开：那样会在旧目录里建新库，旧数据却读不到
            raise BurrowlError("OLD_FORMAT", "这是旧版 burrowl 的数据目录，新版不能直接打开；"
                               "请新建数据目录后用 data.import_v1 导入", {"path": str(self.root)})
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_db = connect(self.root / "ledger.sqlite")
        self.framework_db = connect(self.root / "framework.sqlite")
        self.index_db = connect(self.root / "index.sqlite")
        for conn, name in ((self.ledger_db, "ledger"), (self.framework_db, "framework"), (self.index_db, "index")):
            migrate(conn, name)
        if get_meta(self.ledger_db, "format_version") is None:
            set_meta(self.ledger_db, "created_by", __version__)
        set_meta(self.ledger_db, "format_version", FORMAT_VERSION)  # 迁移执行完，库已是当前格式
        self.ledger = Ledger(self.ledger_db)
        self.framework = Framework(self.framework_db)
        self.index = Index(self.index_db)
        self.blobs = BlobStore(self.root / "blobs")
        self.config = self._load_config()

        # 服务之间的依赖在这里显式装配；各服务只持有 Workspace，不在模块级互相导入
        self.capture = CaptureService(self)
        self.propagation = Propagation(self)
        self.linking = LinkingService(self)
        self.artifacts = ArtifactService(self)
        self.judgments = JudgmentService(self)
        self.frameworks = FrameworkService(self)
        self.retrieval = RetrievalService(self)
        self.agents = AgentService(self)
        self.portability = Portability(self)
        self.import_v1 = ImportV1(self)
        self.overview = OverviewService(self)
        if get_meta(self.index_db, "segmenter_version") != SEGMENTER_VERSION:
            self.rebuild_index()

    def _load_config(self) -> dict:
        path = self.root / "config.json"
        if not path.exists():
            path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        stored = json.loads(path.read_text(encoding="utf-8"))
        return {**DEFAULT_CONFIG, **stored}

    def rebuild_index(self) -> dict:
        """索引可以随时整库重建：从账本和框架重新生成全部索引行。"""
        self.index.clear()
        counts = {"artifacts": 0, "judgments": 0, "records": 0, "pages": 0}
        for art in self.ledger.query("SELECT id FROM artifacts ORDER BY created_at"):
            self.artifacts.index_artifact(art["id"])
            counts["artifacts"] += 1
        for j in self.ledger.query("SELECT id FROM judgments ORDER BY created_at"):
            self.judgments.index_judgment(j["id"])
            counts["judgments"] += 1
        for r in self.ledger.query("SELECT id FROM records ORDER BY created_at"):
            self.artifacts.index_record(r["id"])
            counts["records"] += 1
        for p in self.framework.pages():
            self.frameworks.index_page(p["id"])
            counts["pages"] += 1
        set_meta(self.index_db, "segmenter_version", SEGMENTER_VERSION)
        return counts

    def get(self, entry_id: str) -> dict | None:
        """按 ID 取任意条目（账本或框架）。"""
        prefix = entry_id.split("@", 1)[0].split("#", 1)[0].split("_", 1)[0]
        base = entry_id.split("@", 1)[0].split("#", 1)[0]
        if prefix in ("art", "evt", "rec", "rd", "jdg", "lnk"):
            return self.ledger.get(base)
        if prefix == "pg":
            return self.framework.page(base)
        if prefix == "edg":
            return self.framework.edge(base)
        if prefix == "ent":
            return self.framework.entity(base)
        if prefix == "dec":
            return self.framework.decision(base)
        return None

    def close(self) -> None:
        for conn in (self.ledger_db, self.framework_db, self.index_db):
            conn.close()
