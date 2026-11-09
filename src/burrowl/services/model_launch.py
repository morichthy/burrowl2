"""按需启动本机的 MinerU 服务（设计稿 05 D-19 至 D-21）：用设置里的命令启动、用完空闲后关闭。

- 只有设置 `models.layout_launch=auto`、地址是本机时才启动；命令（`models.layout_cmd`）由人在设置里填写，
  AI 不能修改（`settings.set` 只有人能调用）。burrowl 不打包、不安装 MinerU。
- 启动记录 `cache/models/mineru-launch.json`：进程号、端口、命令、启动时间、最后使用时间。工作台进程与 MCP 进程
  共用一个服务：用之前先查健康检查，已在运行就直接用；用时更新最后使用时间。
- 关闭：启动它的进程在自己的队列空了、且最后使用已过 IDLE_SECONDS 时关闭（连同子进程）。不是自己启动的不关闭；
  启动它的进程退出后，下一个需要它的进程接管启动记录。
- Windows 上在新的命令行窗口里运行（标题"burrowl · MinerU"），可以看到下载模型与处理进度；
  其他系统在后台运行，输出写到 `cache/models/mineru-launch.log`。
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

from ..core.clock import now
from ..core.errors import BurrowlError

IDLE_SECONDS = 600       # 最后使用后空闲这么久就关闭（D-20）
START_TIMEOUT = 1800     # 第一次运行要下载模型，最多等 30 分钟（D-21）
WINDOW_TITLE = "burrowl · MinerU"


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # 按字节比较：tasklist 的输出是系统代码页（中文 Windows 是 GBK），不能按 UTF-8 解码（2026-11-09 实测）
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        return f'"{pid}"'.encode() in (out.stdout or b"")
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        return
    import signal  # noqa: PLC0415
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        pass


class Launcher:
    """一个数据目录里版面引擎服务的启动与关闭。状态（starting / running / stopped / failed）只在本进程内存里。"""

    def __init__(self, models):
        self.models = models
        self._lock = threading.RLock()
        self._own_pid: int | None = None  # 本进程启动（或接管）的服务进程
        self.state: dict = {"state": "stopped"}

    # ---------- 设置 ----------
    @property
    def ws(self):
        return self.models.ws

    def enabled(self) -> bool:
        cfg = self.models.cfg
        url = self.models.url("layout")
        return (cfg.get("layout_launch", "manual") == "auto" and self.models.adapter("layout") == "mineru"
                and bool(url) and self.models.is_local_url(url))

    def command(self) -> list[str]:
        cfg = self.models.cfg
        raw = (cfg.get("layout_cmd") or "").strip() or "mineru-api"
        exe = raw.strip('"')
        found = exe if os.path.isfile(exe) else shutil.which(exe)
        if not found:
            raise BurrowlError("MODEL_NOT_INSTALLED",
                               f"找不到启动命令 {raw}：请先安装 MinerU（uv tool install --python 3.12 "
                               "\"mineru>=4.0,<5\"），或在设置里填写 mineru-api 的完整路径",
                               {"command": raw})
        port = urlparse(self.models.url("layout")).port or 80
        args = [found, "--host", "127.0.0.1", "--port", str(port)]
        tier = cfg.get("layout_tier") or "auto"
        if tier != "auto":
            args += ["--tier", tier]
        return args

    # ---------- 启动记录 ----------
    @property
    def record_path(self):
        return self.ws.root / "cache" / "models" / "mineru-launch.json"

    def record(self) -> dict | None:
        try:
            return json.loads(self.record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_record(self, rec: dict | None) -> None:
        path = self.record_path
        if rec is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

    def touch(self) -> None:
        rec = self.record()
        if rec:
            rec["last_used"] = time.time()
            self._write_record(rec)

    # ---------- 健康检查 ----------
    def healthy(self) -> bool:
        try:
            self.models.health("layout")
            return True
        except BurrowlError:
            return False

    # ---------- 启动与关闭 ----------
    def ensure(self, *, timeout: float = START_TIMEOUT, on_wait=None) -> bool:
        """保证服务在运行。返回 True 表示这次由本进程启动。没有开启自动启动时什么也不做。"""
        if not self.enabled():
            return False
        with self._lock:
            if self.healthy():
                self._adopt()
                self.touch()
                self.state = {"state": "running", "since": self.state.get("since") or now()}
                return False
            rec = self.record()
            if rec and _alive(int(rec.get("pid", 0))):
                pid = int(rec["pid"])  # 别的进程刚启动、还没好：等它
            else:
                pid = self._spawn()
            self.state = {"state": "starting", "since": now(), "pid": pid}
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.healthy():
                with self._lock:
                    self._adopt()
                    self.touch()
                    self.state = {"state": "running", "since": now(), "pid": pid}
                return pid == self._own_pid
            if not _alive(pid):
                self.state = {"state": "failed", "since": now(),
                              "error": "MinerU 启动后退出了；请看它的命令行窗口或 cache/models/mineru-launch.log"}
                self._write_record(None)
                raise BurrowlError("MODEL_UNREACHABLE", self.state["error"])
            if on_wait:
                on_wait()
            time.sleep(2)
        self.state = {"state": "failed", "since": now(), "error": "等 MinerU 启动超时"}
        raise BurrowlError("MODEL_TIMEOUT", "等 MinerU 启动超时（第一次运行要下载模型，可以稍后再试）")

    def _spawn(self) -> int:
        args = self.command()
        log = self.ws.root / "cache" / "models" / "mineru-launch.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            # 新的命令行窗口：用户能看到下载与处理进度（D-19）；title 让窗口好认
            line = subprocess.list2cmdline(args)
            proc = subprocess.Popen(f'cmd /c "title {WINDOW_TITLE} && {line}"',
                                    creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            with log.open("ab") as fh:
                proc = subprocess.Popen(args, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        self._own_pid = proc.pid
        self._write_record({"pid": proc.pid, "owner_pid": os.getpid(), "command": args,
                            "started_at": time.time(), "last_used": time.time()})
        return proc.pid

    def _adopt(self) -> None:
        """启动记录的主人已经退出：由本进程接管，之后由本进程负责空闲关闭。"""
        rec = self.record()
        if not rec:
            return
        if int(rec.get("owner_pid", 0)) == os.getpid():
            self._own_pid = int(rec["pid"])
        elif not _alive(int(rec.get("owner_pid", 0))) and _alive(int(rec.get("pid", 0))):
            rec["owner_pid"] = os.getpid()
            self._write_record(rec)
            self._own_pid = int(rec["pid"])

    def owns(self) -> bool:
        rec = self.record()
        return bool(rec and self._own_pid and int(rec.get("pid", 0)) == self._own_pid
                    and int(rec.get("owner_pid", 0)) == os.getpid())

    def stop(self, *, force: bool = False) -> bool:
        """关闭本进程启动的服务。force=True（人在设置页点"关闭"）时也关闭别的进程记下的服务。"""
        with self._lock:
            rec = self.record()
            if not rec or not (force or self.owns()):
                return False
            _kill_tree(int(rec["pid"]))
            self._write_record(None)
            self._own_pid = None
            self.state = {"state": "stopped", "since": now()}
            return True

    def maybe_stop_idle(self) -> bool:
        """队列空闲时调用：本进程启动的服务最后使用已过 IDLE_SECONDS 就关闭（D-20）。"""
        rec = self.record()
        if not rec or not self.owns():
            return False
        if time.time() - float(rec.get("last_used", 0)) < IDLE_SECONDS:
            return False
        return self.stop()

    def status(self) -> dict:
        rec = self.record()
        out = {"enabled": self.enabled(), **self.state}
        if rec:
            out.update(pid=rec.get("pid"), owned=self.owns(),
                       idle_seconds=int(time.time() - float(rec.get("last_used", time.time()))))
        return out
