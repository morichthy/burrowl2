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
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .. import FORMAT_VERSION, __version__
from ..core.errors import BurrowlError
from ..index.fts import Index
from ..index.segment import SEGMENTER_VERSION
from ..index.tokenize import TOKENIZER_VERSION
from ..index.units import CONTEXT_CHARS, UNITS_VERSION
from ..index.units import MAX as UNITS_MAX
from ..index.units import TARGET as UNITS_TARGET
from ..store.blobs import BlobStore
from ..store.db import connect, get_meta, migrate, set_meta
from ..store.framework import Framework
from ..store.ledger import Ledger
from .agents import AGENT_CLI_PRESETS, AgentService
from .artifacts import ArtifactService
from .associate import AssociateService
from .capture import CaptureService
from .checks import SourceCheck
from .coordinates import CoordinateService
from .coverage import CoverageService
from .digest import DEFAULTS as DIGEST_DEFAULTS
from .digest import DigestService
from .extraction import ExtractionService
from .framework import FrameworkService
from .inspection import DEFAULTS as INSPECTION_DEFAULTS
from .inspection import InspectionService
from .judgments import JudgmentService
from .linking import LinkingService
from .models import ModelService
from .overview import OverviewService
from .portability import Portability
from .propagation import Propagation
from .purge import PurgeService
from .recognition import RecognitionReview
from .relations import RelationService
from .retrieval import RETRIEVAL_DEFAULTS, RetrievalService
from .review import ReviewService
from .vectors import VectorService
from .versions import VersionService

DEFAULT_CONFIG = {
    # agent 命令模板：{prompt} 为任务文本，{mcp_config} 为本数据目录生成的 MCP 配置文件路径（DESIGN §3.3 第 6 步）
    "agents": {name: {"command": command.copy(), "cli_type": name} for name, command in AGENT_CLI_PRESETS.items()},
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
    # units_*：检索单元的目标长度、上限（token 估计）与机械上下文字数（设计稿 06 D-22）；改了要重建索引。
    # 打开重排时上限不超过 400、上下文不超过 160 字（重排模型的输入上限 512 token 含查询与上下文）
    "index": {"multimodal_model": "none", "embedding_model": "jina-v2-base-zh", "rerank": "off",
              "units_target": UNITS_TARGET, "units_max": UNITS_MAX, "units_context_chars": CONTEXT_CHARS},
    # 检索参数（设计稿 06 D-21）：只影响查询、不用重建索引；工作台与 AI（MCP、命令行）读同一份，
    # 保存后各进程下一次调用就生效（WorkspacePool.get → refresh_config）。
    # 默认值与说明在 services/retrieval.py 的 RETRIEVAL_DEFAULTS，取值范围见 ops 的 SETTING_NUMBERS
    "retrieval": dict(RETRIEVAL_DEFAULTS),
    # AI 复核（设计稿 04 D-15）：off 不接受 / framework 只接受框架页与关联边 / all 再加上待复核的判断
    # sample_size：每周抽查的 AI 生成未复核框架页数（D-07）
    "review": {"ai": "framework", "sample_size": 5},
    # 本地模型与大模型（设计稿 05）：layout 版面抽取（none / mineru）、formula 公式识别（none / follow_layout）、
    # llm 通用大模型（none / openai，OpenAI 兼容接口，只在人显式点击时调用）。向量模型见上面的 index.embedding_model
    # （设计稿 06，进程内加载本机的 ONNX 模型）。*_auto：本地模型在登记、补抽后是否自动运行（地址必须是本机）
    "models": {"layout": "none", "layout_url": "", "layout_mode": "formulas", "layout_auto": "on",
               "layout_tier": "auto", "formula": "follow_layout",
               "llm": "none", "llm_url": "", "llm_model": "", "llm_key": "", "llm_agent": ""},
    # 定期巡检（设计稿 08）：interval_days 定时准备巡检包的周期（天，0 关闭）；max_segments 一期的阅读预算（段落）；
    # explore_ratio 其中用于探索样本的比例；window_days / hit_min 检索命中记录的统计窗口与"命中未读"的次数；
    # related_min "相关未读"的向量相似度下限；uncaptured_max 每期最多几组"经验未收录"任务（0 关闭，D-40）；
    # inspector / reviewer 巡检员、复核员 agent（agents 里的名称）；
    # framework_words 规则检查的评价性措辞（逗号分隔）。定时只准备，不调用大模型（D-01）
    "inspection": dict(INSPECTION_DEFAULTS),
    # 消化外部材料（设计稿 09 D-07）：max_claims 每份材料最多收几条论断
    "digest": dict(DIGEST_DEFAULTS),
}


class Workspace:
    # 分段、切词、检索单元的规则任何一个变了，启动时整库重建索引（向量缓存按内容指纹保留，设计稿 06 D-07）
    INDEX_VERSION = f"seg{SEGMENTER_VERSION}-{TOKENIZER_VERSION}-units{UNITS_VERSION}"

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        if (self.root / ".burrowl").is_dir() and not (self.root / "ledger.sqlite").exists():
            # 防止把旧版数据目录当成新版打开：那样会在旧目录里建新库，旧数据却读不到
            raise BurrowlError("OLD_FORMAT", "这是旧版 burrowl 的数据目录，新版不能直接打开；"
                               "请新建数据目录", {"path": str(self.root)})
        _refuse_old_ledger(self.root / "ledger.sqlite")
        self.root.mkdir(parents=True, exist_ok=True)
        # 三个 SQLite 连接由多个线程共用（工作台的请求线程、定时检查、agent 输出线程）。
        # 同一连接上并行的查询会互相打乱结果，所以对一个数据目录的操作一律在这把锁里进行：
        # 操作入口（registry.call）、工作台的文件接口、定时检查、agent 结束登记都先取锁。可重入。
        self.lock = threading.RLock()
        # 后台重建索引（start_rebuild）的状态；只在本进程里
        self._rebuild: dict | None = None
        self._rebuild_thread: threading.Thread | None = None
        self._rebuild_guard = threading.Lock()
        self._closing = threading.Event()
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
        self.relations = RelationService(self)
        self.coordinates = CoordinateService(self)
        self.capture = CaptureService(self)
        self.propagation = Propagation(self)
        self.linking = LinkingService(self)
        self.artifacts = ArtifactService(self)
        self.extraction = ExtractionService(self)
        self.judgments = JudgmentService(self)
        self.versions = VersionService(self)
        self.purge = PurgeService(self)
        self.frameworks = FrameworkService(self)
        self.reviews = ReviewService(self)
        self.models = ModelService(self)
        self.recognition = RecognitionReview(self)
        self.retrieval = RetrievalService(self)
        self.vectors = VectorService(self)
        self.associate = AssociateService(self)
        self.agents = AgentService(self)
        self.inspection = InspectionService(self)
        self.coverage = CoverageService(self)
        self.digest = DigestService(self)
        self.portability = Portability(self)
        self.overview = OverviewService(self)
        self.source_check = SourceCheck(self)
        if get_meta(self.index_db, "index_version") != self.index_version():
            self.rebuild_index()

    def _load_config(self) -> dict:
        path = self.root / "config.json"
        if not path.exists():
            path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        self._config_stamp = _stamp(path)
        stored = json.loads(path.read_text(encoding="utf-8"))
        # 分组的配置按键合并：旧 config.json 没有的新键取默认值
        return {k: ({**v, **stored.get(k, {})} if isinstance(v, dict) and k != "agents" else stored.get(k, v))
                for k, v in DEFAULT_CONFIG.items()} | {k: v for k, v in stored.items() if k not in DEFAULT_CONFIG}

    def save_config(self, changes: dict, *, replace: tuple[str, ...] = ()) -> dict:
        """按组更新配置并写回 config.json（先写临时文件再改名）。replace 中的组整体替换，用于删除组内的键。"""
        path = self.root / "config.json"
        stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        for key, value in changes.items():
            merge = isinstance(value, dict) and key not in replace
            stored[key] = {**stored.get(key, {}), **value} if merge else value
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        self.config = self._load_config()
        return self.config

    def unit_options(self) -> dict:
        """检索单元的长度参数（设计稿 06 D-22）：config.json 的 index.units_*，传给 build_units。"""
        idx = self.config.get("index", {})
        return {"target": int(idx.get("units_target", UNITS_TARGET)),
                "max_tokens": int(idx.get("units_max", UNITS_MAX)),
                "context_chars": int(idx.get("units_context_chars", CONTEXT_CHARS))}

    def index_version(self) -> str:
        """当前索引应有的版本：规则版本，加上非默认的检索单元长度。默认值不写进去，已有数据目录升级时不重建。"""
        o = self.unit_options()
        if (o["target"], o["max_tokens"], o["context_chars"]) == (UNITS_TARGET, UNITS_MAX, CONTEXT_CHARS):
            return self.INDEX_VERSION
        return f"{self.INDEX_VERSION}-t{o['target']}m{o['max_tokens']}c{o['context_chars']}"

    def index_stale(self) -> bool:
        """索引是不是按别的检索单元长度建的（例如另一个进程刚改了设置、还在重建）。"""
        return get_meta(self.index_db, "index_version") != self.index_version()

    def refresh_config(self) -> bool:
        """config.json 被别的进程改过（工作台保存设置、命令行 settings.set）就重新读取，返回是否重读。
        MCP 进程长期持有 Workspace：不重读的话，人在工作台改的检索参数要等客户端重启才对 AI 生效。"""
        path = self.root / "config.json"
        if _stamp(path) == getattr(self, "_config_stamp", None):
            return False
        try:
            self.config = self._load_config()
        except (OSError, ValueError):  # 别的进程正在写（先写临时文件再改名，几乎碰不到）：沿用旧配置，下次再读
            return False
        return True

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

    def _index_tasks(self) -> list[tuple[str, str]]:
        """要建索引的全部条目：(类别, ID)，类别是 artifacts / judgments / records / pages。"""
        tasks = [("artifacts", r["id"]) for r in self.ledger.query("SELECT id FROM artifacts ORDER BY created_at")]
        tasks += [("judgments", r["id"]) for r in self.ledger.query("SELECT id FROM judgments ORDER BY created_at")]
        tasks += [("records", r["id"]) for r in self.ledger.query("SELECT id FROM records ORDER BY created_at")]
        tasks += [("pages", p["id"]) for p in self.framework.pages()]
        return tasks

    def _index_one(self, kind: str, entry_id: str) -> None:
        {"artifacts": self.artifacts.index_artifact, "judgments": self.judgments.index_judgment,
         "records": self.artifacts.index_record, "pages": self.frameworks.index_page}[kind](entry_id)

    def rebuild_index(self) -> dict:
        """索引可以随时整库重建：从账本和框架重新生成全部索引行。同步执行，调用方持有锁期间别的请求都要等；
        工作台里改设置、点"重建"用 start_rebuild（后台、逐条取锁）。"""
        self.index.clear()
        counts = {"artifacts": 0, "judgments": 0, "records": 0, "pages": 0}
        for kind, entry_id in self._index_tasks():
            self._index_one(kind, entry_id)
            counts[kind] += 1
        set_meta(self.index_db, "segmenter_version", SEGMENTER_VERSION)
        set_meta(self.index_db, "index_version", self.index_version())
        return counts

    # ---------- 后台重建（设计稿 06 D-22）：逐条取锁，期间其他请求照常；旧索引行逐条被替换，不先清空 ----------
    def start_rebuild(self, reason: str = "") -> dict:
        """在后台线程里重建全部索引行。已经在重建时，记下"完成后再来一遍"（期间设置又变了）。返回当前状态。"""
        with self._rebuild_guard:
            job = self._rebuild
            if job and job["state"] == "running":
                job["again"] = True
                job["reason"] = reason or job["reason"]
                return self.rebuild_status()
            self._rebuild = {"state": "running", "reason": reason, "done": 0, "total": 0, "errors": [],
                             "started_at": _now(), "finished_at": None, "again": False}
            thread = threading.Thread(target=self._rebuild_worker, name="index-rebuild", daemon=True)
            self._rebuild_thread = thread
            thread.start()
        return self.rebuild_status()

    def rebuild_status(self) -> dict | None:
        """本进程里最近一次后台重建：state running / done / failed，done / total 条，errors 出错的条目。"""
        job = self._rebuild
        return None if job is None else {k: (list(v) if isinstance(v, list) else v) for k, v in job.items()}

    def wait_rebuild(self, timeout: float | None = None) -> dict | None:
        """等后台重建结束（测试、命令行用）。"""
        thread = self._rebuild_thread
        if thread is not None:
            thread.join(timeout)
        return self.rebuild_status()

    def _rebuild_worker(self) -> None:
        job = self._rebuild
        try:
            while True:
                with self.lock:
                    tasks = self._index_tasks()
                job.update(total=len(tasks), done=0, again=False)
                for kind, entry_id in tasks:
                    if self._closing.is_set():
                        job.update(state="failed", finished_at=_now(), errors=[*job["errors"], "数据目录已关闭"][-20:])
                        return
                    with self.lock:  # 每条单独取锁：两条之间别的请求可以插进来
                        try:
                            self._index_one(kind, entry_id)
                        except Exception as exc:  # noqa: BLE001 —— 一条出错不影响其他条目，记下来
                            job["errors"] = [*job["errors"], f"{entry_id}: {type(exc).__name__}: {exc}"][-20:]
                    job["done"] += 1
                # 先取数据目录的锁再取 guard：与 settings.set（持锁时调 start_rebuild）的顺序一致，避免互相等
                with self.lock, self._rebuild_guard:
                    if job["again"]:  # 重建期间设置又变了：按新设置再来一遍
                        continue
                    set_meta(self.index_db, "segmenter_version", SEGMENTER_VERSION)
                    set_meta(self.index_db, "index_version", self.index_version())
                    job.update(state="done", finished_at=_now())
                    return
        except Exception as exc:  # noqa: BLE001 —— 后台线程不能把异常抛给谁：记在状态里，首页能看到
            job.update(state="failed", finished_at=_now(),
                       errors=[*job["errors"], f"{type(exc).__name__}: {exc}"][-20:])

    def get(self, entry_id: str) -> dict | None:
        """按引用取任意条目（账本或框架）。账本条目带 `@n` 时取那一版，否则取当前版。"""
        prefix = entry_id.split("@", 1)[0].split("#", 1)[0].split("_", 1)[0]
        base = entry_id.split("@", 1)[0].split("#", 1)[0]
        if prefix in ("art", "evt", "rec", "rd", "jdg", "rel", "vst", "ex", "rev", "rpl", "pol"):
            return self.ledger.get(entry_id.split("#", 1)[0])
        if prefix == "pg":
            return self.framework.page(base)
        if prefix == "edg":
            return self.framework.edge(base)
        if prefix == "ent":
            return self.framework.entity(base)
        if prefix == "dec":
            return self.framework.decision(base)
        if prefix == "insp":
            return self.framework.inspection(base)
        return None

    def close(self) -> None:
        self._closing.set()
        if self._rebuild_thread is not None:
            self._rebuild_thread.join(10)
        for conn in (self.ledger_db, self.framework_db, self.index_db):
            conn.close()


def _stamp(path: Path) -> tuple[int, int] | None:
    """config.json 的修改时间与大小：变了就说明被别的进程改过。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _refuse_old_ledger(path: Path) -> None:
    """2.0.x 的数据目录（设计稿 10 D-03）：账本里有已执行的迁移，却没有 relations 表。只读打开检查，不做任何写入。"""
    if not path.exists():
        return
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    finally:
        conn.close()
    if "schema_migrations" in names and "relations" not in names:
        raise BurrowlError("OLD_FORMAT", "这是 2.0 的数据目录，2.1 不能打开；请新建数据目录（burrowl init <新目录>）",
                           {"path": str(path.parent)})
