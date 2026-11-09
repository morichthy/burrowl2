"""组合根：按数据目录装配存储与各服务。

数据目录布局：
    ledger.sqlite      原件与判断（只追加，唯一不可替代的部分）
    framework.sqlite   框架层（可再生）
    index.sqlite       检索索引：引用段落、检索单元、向量缓存（可删除重建）
    blobs/             内容寻址的原件文件（含嵌入图片、页面快照 PDF）
    cache/             可随时删除的派生缓存（页面图像）
    config.json        配置（agent 命令模板等）
"""
import json
import threading
from contextlib import contextmanager
from pathlib import Path

from .. import FORMAT_VERSION, __version__
from ..core.errors import BurrowlError
from ..index.fts import Index
from ..index.segment import SEGMENTER_VERSION
from ..index.tokenize import TOKENIZER_VERSION
from ..index.units import UNITS_VERSION
from ..store.blobs import BlobStore
from ..store.db import connect, get_meta, migrate, set_meta
from ..store.framework import Framework
from ..store.ledger import Ledger
from .agents import AgentService
from .artifacts import ArtifactService
from .associate import AssociateService
from .capture import CaptureService
from .checks import SourceCheck
from .extraction import ExtractionService
from .framework import FrameworkService
from .import_v1 import ImportV1
from .judgments import JudgmentService
from .linking import LinkingService
from .models import ModelService
from .overview import OverviewService
from .portability import Portability
from .propagation import Propagation
from .recognition import RecognitionReview
from .retrieval import RetrievalService
from .review import ReviewService
from .vectors import VectorService

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
    # 外部原件定时检查间隔（小时）；0 关闭（services/checks.py）
    "artifact_check": {"interval_hours": 6},
    # 抽取方式（设计稿 01 D-11、D-17）：pdf / pptx / docx 为 auto（登记时用内置抽取器）或 off；
    # image / av 只能 on_demand（人手动指定或 AI 明确调用时抽取）；snapshot 为页面快照的转换器
    # auto（Office 优先，其次 LibreOffice）/ office / libreoffice / none
    "extraction": {"pdf": "auto", "pptx": "auto", "docx": "auto", "xlsx": "auto", "image": "on_demand",
                   "av": "on_demand",
                   "snapshot": "auto"},
    # 阅读模式每种格式默认用哪个阅读器（设计稿 03 D-14）；取值是前端 reader/registry.ts 里的阅读器名称
    # onlyoffice_*：外部引擎 ONLYOFFICE Docs 的地址、引擎访问 burrowl 用的地址（空 = 浏览器访问工作台的地址）、JWT 密钥
    "viewer": {"pdf": "pdfjs", "docx": "docx-preview", "pptx": "pdfjs-snapshot", "xlsx": "sheet", "text": "markdown",
               "image": "image", "av": "media", "onlyoffice_url": "", "onlyoffice_burrowl_url": "",
               "onlyoffice_secret": ""},
    # 检索索引方式：文字索引总是建立；multimodal_model 为多模态索引模型，none 不建（尚未实现，设计稿 01 D-18）；
    # embedding_model 为向量通道的模型（none 不建，设计稿 06 D-07）；rerank 为 auto（装了重排模型就重排）或 off。
    # 重排默认 off：回归题上本机的重排模型让段落命中从 8/12 降到 7/12，每次检索多约 1 秒（设计稿 06 D-08 修订）
    "index": {"multimodal_model": "none", "embedding_model": "jina-v2-base-zh", "rerank": "off"},
    # AI 复核（设计稿 04 D-15）：off 不接受 / framework 只接受框架页与关联边 / all 再加上待复核的判断
    # sample_size：每周抽查的 AI 生成未复核框架页数（D-07）
    "review": {"ai": "framework", "sample_size": 5},
    # 本地模型与大模型（设计稿 05）：layout 版面抽取（none / mineru）、formula 公式识别（none / follow_layout）、
    # llm 通用大模型（none / openai，OpenAI 兼容接口，只在人显式点击时调用）。向量模型见上面的 index.embedding_model
    # （设计稿 06，进程内加载本机的 ONNX 模型）。*_auto：本地模型在登记、补抽后是否自动运行（地址必须是本机）
    "models": {"layout": "none", "layout_url": "", "layout_mode": "formulas", "layout_auto": "on",
               "layout_tier": "auto", "formula": "follow_layout",
               "llm": "none", "llm_url": "", "llm_model": "", "llm_key": ""},
}


class Workspace:
    # 分段、切词、检索单元的规则任何一个变了，启动时整库重建索引（向量缓存按内容指纹保留，设计稿 06 D-07）
    INDEX_VERSION = f"seg{SEGMENTER_VERSION}-{TOKENIZER_VERSION}-units{UNITS_VERSION}"

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        if (self.root / ".burrowl").is_dir() and not (self.root / "ledger.sqlite").exists():
            # 防止把旧版数据目录当成新版打开：那样会在旧目录里建新库，旧数据却读不到
            raise BurrowlError("OLD_FORMAT", "这是旧版 burrowl 的数据目录，新版不能直接打开；"
                               "请新建数据目录后用 data.import_v1 导入", {"path": str(self.root)})
        self.root.mkdir(parents=True, exist_ok=True)
        # 三个 SQLite 连接由多个线程共用（工作台的请求线程、定时检查、agent 输出线程）。
        # 同一连接上并行的查询会互相打乱结果，所以对一个数据目录的操作一律在这把锁里进行：
        # 操作入口（registry.call）、工作台的文件接口、定时检查、agent 结束登记都先取锁。可重入。
        self.lock = threading.RLock()
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
        self.extraction = ExtractionService(self)
        self.judgments = JudgmentService(self)
        self.frameworks = FrameworkService(self)
        self.reviews = ReviewService(self)
        self.models = ModelService(self)
        self.recognition = RecognitionReview(self)
        self.retrieval = RetrievalService(self)
        self.vectors = VectorService(self)
        self.associate = AssociateService(self)
        self.agents = AgentService(self)
        self.portability = Portability(self)
        self.import_v1 = ImportV1(self)
        self.overview = OverviewService(self)
        self.source_check = SourceCheck(self)
        if get_meta(self.index_db, "index_version") != self.INDEX_VERSION:
            self.rebuild_index()
        # 旧版写成判断的复核、退役记录是变更历史，不进检索（2.0.0a14）；索引可再生，直接去掉
        for r in self.ledger.query("SELECT id FROM judgments WHERE kind IN ('review', 'retirement')"):
            self.index.remove(r["id"])

    def _load_config(self) -> dict:
        path = self.root / "config.json"
        if not path.exists():
            path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        stored = json.loads(path.read_text(encoding="utf-8"))
        # 分组的配置按键合并：旧 config.json 没有的新键取默认值
        return {k: ({**v, **stored.get(k, {})} if isinstance(v, dict) and k != "agents" else stored.get(k, v))
                for k, v in DEFAULT_CONFIG.items()} | {k: v for k, v in stored.items() if k not in DEFAULT_CONFIG}

    def save_config(self, changes: dict) -> dict:
        """按组更新配置并写回 config.json（先写临时文件再改名）。"""
        path = self.root / "config.json"
        stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        for key, value in changes.items():
            stored[key] = {**stored.get(key, {}), **value} if isinstance(value, dict) else value
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        self.config = self._load_config()
        return self.config

    @contextmanager
    def unlocked(self):
        """长时间的外部操作（如用 Office 生成页面快照）期间暂时放开锁，让其他请求继续；结束后重新取锁。
        只在本线程持有锁时生效；没有持有时什么也不做。"""
        try:
            self.lock.release()
            released = True
        except RuntimeError:
            released = False
        try:
            yield
        finally:
            if released:
                self.lock.acquire()

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
        set_meta(self.index_db, "index_version", self.INDEX_VERSION)
        return counts

    def get(self, entry_id: str) -> dict | None:
        """按 ID 取任意条目（账本或框架）。"""
        prefix = entry_id.split("@", 1)[0].split("#", 1)[0].split("_", 1)[0]
        base = entry_id.split("@", 1)[0].split("#", 1)[0]
        if prefix in ("art", "evt", "rec", "rd", "jdg", "lnk", "ex", "rev", "ret"):
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
