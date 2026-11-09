"""F9 agent 运行器：在工作台直接启动本机 agent CLI（Claude Code、Codex 等）。

- 服务端不直接调用模型 API；AI 工作由 agent 通过 MCP 回到本服务完成（DESIGN §3.1）。
- 每次运行生成独立的 MCP 配置，带上本次运行的身份和会话（BURROWL_ACTOR_ID / BURROWL_SESSION），
  所以 agent 写的内容作者记为这次运行的 AI，过程日志落在这次运行的会话里。
- 输出实时写入内存缓冲与 runs/<编号>/output.log，工作台用 SSE 读取。运行日志独立保存。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import new_id

PREAMBLE = (
    "你在 burrowl 工作区中工作，通过 MCP 服务 burrowl 的工具读写记录。规则：\n"
    "日常工程、科研和其他重要或经常性工作，只收录对以后有用的原件和判断；普通对话与执行流水留在运行日志。\n"
    "1. 原件只记原文；判断写清对象和条件，并用 cites 引用依据（原件、事实记录、读取记录或判断），不能引用框架页；\n"
    "   判断类型只有 conclusion 结论、process 过程（提问、尝试、停下的路线）、normative 规定；\n"
    "   过程内容不能作为结论的依据；\n"
    "2. 你不能更正或撤回判断；有值得留存的异议时，写一条 opposes 关系的新判断；\n"
    "3. 对某个设备或对象动手前，先调用 constraints_check；\n"
    "4. 框架页（实体页、综合页）写入时给出 inputs 输入清单。\n\n任务：\n"
)


class AgentService:
    def __init__(self, ws):
        self.ws = ws
        self._buffers: dict[str, list[str]] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def agents(self) -> list[dict]:
        from .workspace import DEFAULT_CONFIG  # noqa: PLC0415
        out = []
        for name, spec in self.ws.config["agents"].items():
            exe = spec["command"][0]
            default = DEFAULT_CONFIG["agents"].get(name, {}).get("command", [exe])[0]
            resolved = shutil.which(exe)
            out.append({"name": name, "command": spec["command"], "executable": exe, "default_executable": default,
                        "resolved": resolved, "available": resolved is not None,
                        "found": [p for p in find_candidates(Path(default).name) if p != resolved]})
        return out

    def save_command(self, actor: Actor, *, agent: str, command: list[str]) -> dict:
        """新增或替换启动模板。首项是程序，其余项原样作为独立参数传入。"""
        actor.require_human("配置 agent 命令")
        agent = agent.strip()
        if not re.fullmatch(r"[\w.-]{1,64}", agent) and agent not in self.ws.config["agents"]:
            raise BurrowlError("INVALID_ARGUMENT", "名称请使用 1 到 64 个字母、数字、汉字、下划线、点或连字符")
        if not command or not command[0].strip() or any("\0" in part for part in command):
            raise BurrowlError("INVALID_ARGUMENT", "请填写可执行文件，命令中不能包含空字符")
        executable = command[0].strip().strip('"')
        if not executable or any(c in executable for c in '&|<>^\n\r"{}'):
            raise BurrowlError("INVALID_ARGUMENT", "首项只填命令名或可执行文件的完整路径")
        if not any("{prompt}" in part for part in command[1:]):
            raise BurrowlError("INVALID_ARGUMENT", "启动参数须包含 {prompt}，用来传入本次任务")
        command = [executable, *command[1:]]
        # 保留旧配置中的其他字段和模板。找不到程序也可先保存，启动前会再检查。
        agents = self.ws.config["agents"]
        spec = agents.get(agent, {})
        old = spec.get("command")
        if old != command:
            self.ws.save_config({"agents": {**agents, agent: {**spec, "command": command}}})
            self.ws.capture.log(actor, "settings.set",
                                input={"changes": {f"agents.{agent}.command": {"from": old, "to": command}}})
        return next(a for a in self.agents() if a["name"] == agent)

    def set_executable(self, actor: Actor, *, agent: str, executable: str) -> dict:
        """改一个 agent 命令模板里的可执行文件（命令名或完整路径，设计稿 08 D-39）；其余参数不变。
        留空恢复默认命令名。只有人能改；记一条过程日志 settings.set。"""
        from .workspace import DEFAULT_CONFIG  # noqa: PLC0415
        actor.require_human("修改 agent 命令")
        agents = {k: dict(v) for k, v in self.ws.config["agents"].items()}
        spec = agents.get(agent)
        if spec is None:
            raise BurrowlError("NOT_FOUND", "没有配置这个 agent", {"agent": agent, "known": list(agents)})
        value = (executable or "").strip().strip('"')
        restore = not value
        if restore:
            value = DEFAULT_CONFIG["agents"].get(agent, {}).get("command", spec["command"])[0]
        if any(c in value for c in "&|<>^\n\r\"") or "{" in value:
            raise BurrowlError("INVALID_ARGUMENT", "只填可执行文件（命令名或完整路径），不能带参数或 & | < > 等符号")
        if not restore and shutil.which(value) is None:
            raise BurrowlError("AGENT_NOT_FOUND", f"找不到 {value}：请填完整路径，或先安装这个命令", {"agent": agent})
        old = spec["command"][0]
        spec["command"] = [value, *spec["command"][1:]]
        self.ws.save_config({"agents": agents})
        if old != value:
            self.ws.capture.log(actor, "settings.set",
                                input={"changes": {f"agents.{agent}.command[0]": {"from": old, "to": value}}})
        return next(a for a in self.agents() if a["name"] == agent)

    def mcp_config(self, actor_id: str, session_id: str, path: Path) -> Path:
        config = {"mcpServers": {"burrowl": {
            "command": sys.executable, "args": ["-m", "burrowl", "mcp", "--data", str(self.ws.root)],
            "env": {"BURROWL_ACTOR_ID": actor_id, "BURROWL_SESSION": session_id},
        }}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def start(self, actor: Actor, *, agent: str, prompt: str, cwd: str | None = None,
              preamble: bool = True, inspection_id: str | None = None, inspection_role: str | None = None) -> dict:
        actor.require_human("启动 agent")
        spec = self.ws.config["agents"].get(agent)
        if spec is None:
            raise BurrowlError("NOT_FOUND", "没有配置这个 agent",
                               {"agent": agent, "known": list(self.ws.config["agents"])})
        exe = shutil.which(spec["command"][0])
        if exe is None:
            raise BurrowlError("AGENT_NOT_FOUND", f"找不到命令 {spec['command'][0]}，请先安装或在 config.json 中修改",
                               {"agent": agent})
        run_id, session_id = new_id("run"), new_id("ses")
        run_dir = self.ws.root / "runs" / run_id
        agent_actor = f"ai:{agent}:{run_id}"
        mcp_path = self.mcp_config(agent_actor, session_id, run_dir / "mcp.json")
        text = (PREAMBLE if preamble else "") + prompt
        # 只替换模板里的占位符，任务正文中出现的同名文字保持原样。
        replacements = {"{prompt}": text, "{mcp_config}": str(mcp_path)}
        command = [exe, *(re.sub(r"\{prompt\}|\{mcp_config\}", lambda match: replacements[match[0]], part)
                          for part in spec["command"][1:])]
        workdir = Path(cwd).expanduser() if cwd else self.ws.root
        self.ws.framework.add_run(run_id, agent, session_id, {
            "prompt": prompt, "command": spec["command"], "cwd": str(workdir), "started_by": actor.id,
            "agent_actor": agent_actor,
            # 在子进程启动前登记身份，首个 MCP 请求也能识别巡检会话。
            **({"inspection_id": inspection_id, "inspection_role": inspection_role} if inspection_id else {})})
        self.ws.capture.log(actor, "agent.start", input={"run_id": run_id, "agent": agent, "prompt": prompt})
        # 子进程输出统一为 UTF-8（Windows 默认是 GBK）
        env = {**os.environ, "BURROWL_ACTOR_ID": agent_actor, "BURROWL_SESSION": session_id,
               "BURROWL_DATA": str(self.ws.root), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                cwd=workdir, env=env, text=True, encoding="utf-8", errors="replace", bufsize=1)
        with self._lock:
            self._buffers[run_id] = []
            self._procs[run_id] = proc
        threading.Thread(target=self._pump, args=(run_id, proc, run_dir), daemon=True).start()
        return self.ws.framework.run(run_id)

    def _pump(self, run_id: str, proc: subprocess.Popen, run_dir: Path) -> None:
        log = (run_dir / "output.log").open("a", encoding="utf-8")
        try:
            for line in proc.stdout:
                with self._lock:
                    self._buffers[run_id].append(line)
                log.write(line)
                log.flush()
            code = proc.wait()
        finally:
            log.close()
        self._finish(run_id, code)

    def _finish(self, run_id: str, code: int) -> None:
        with self.ws.lock:  # 与请求线程共用连接。输出留在 output.log，不进入原件层。
            status = "done" if code == 0 else ("cancelled" if self.ws.framework.run(run_id)["status"] == "cancelling"
                                                else "failed")
            self.ws.framework.finish_run(run_id, status, {"exit_code": code})
        with self._lock:
            self._procs.pop(run_id, None)

    def output(self, run_id: str, offset: int = 0) -> dict:
        with self.ws.lock:
            run = self.ws.framework.run(run_id)
        if run is None:
            raise BurrowlError("NOT_FOUND", "没有这次运行", {"run_id": run_id})
        with self._lock:
            lines = self._buffers.get(run_id)
            if lines is None:  # 进程重启后从文件读
                path = self.ws.root / "runs" / run_id / "output.log"
                lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
            chunk = lines[offset:]
        return {"run": run, "lines": chunk, "offset": offset + len(chunk), "running": run["status"] == "running"}

    def cancel(self, actor: Actor, run_id: str) -> dict:
        actor.require_human("停止 agent")
        with self._lock:
            proc = self._procs.get(run_id)
        if proc is None:
            raise BurrowlError("CONFLICT", "这次运行已经结束", {"run_id": run_id})
        self.ws.framework.finish_run(run_id, "cancelling", {})
        proc.terminate()
        return {"run_id": run_id, "status": "cancelling"}

    # ---------- 测试连接（设计稿 08 D-26） ----------
    def test(self, actor: Actor, *, agent: str, timeout: float = 180) -> dict:
        """分三步测一个 agent：① 命令能找到，--version 用于诊断；② 用一句短提示启动一次，让它经 MCP 调用
        system_status 并原样输出 actor；③ 核对输出里的身份是这次运行的 ai:… 身份。
        等待期间放开数据目录的锁，让输出线程更新运行状态。"""
        actor.require_human("测试 agent 连接")
        spec = self.ws.config["agents"].get(agent)
        if spec is None:
            raise BurrowlError("NOT_FOUND", "没有配置这个 agent",
                               {"agent": agent, "known": list(self.ws.config["agents"])})
        steps: list[dict] = []
        exe = shutil.which(spec["command"][0])
        t0 = time.monotonic()
        if exe is None:
            steps.append({"step": "command", "ok": False,
                          "detail": f"找不到命令 {spec['command'][0]}：在设置页“巡检”里填它的完整路径，或先安装"})
            return {"agent": agent, "ok": False, "steps": steps}
        try:
            # 命令模板开头若是"解释器 + 脚本文件"（python fake.py），把 --version 交给脚本
            lead = []
            for part in spec["command"][1:]:
                if "{" in part or not Path(part).is_file():
                    break
                lead.append(part)
            proc = subprocess.run([exe, *lead, "--version"], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=30, stdin=subprocess.DEVNULL)
            version = (proc.stdout or proc.stderr or "").strip().splitlines()[:1]
            detail = version[0] if version else exe
            if proc.returncode != 0:
                detail = f"已找到命令，--version 返回 {proc.returncode}：{detail}"
            steps.append({"step": "command", "ok": True, "detail": detail,
                          "seconds": round(time.monotonic() - t0, 1)})
        except OSError as exc:
            steps.append({"step": "command", "ok": False, "detail": f"无法启动命令：{exc}"})
            return {"agent": agent, "ok": False, "steps": steps}
        except subprocess.TimeoutExpired:
            # 自定义启动器未必支持 --version，实际启动与身份检查才决定连接是否成功。
            steps.append({"step": "command", "ok": True, "detail": "已找到命令，版本探测超时"})
        t1 = time.monotonic()
        run = self.start(actor, agent=agent, preamble=False,
                         prompt="这是 burrowl 的连接测试。请调用 MCP 服务 burrowl 的 system_status 工具，"
                                "只输出它返回的 actor.id 一行，不做其他任何事。")
        with self.ws.unlocked():
            try:
                done = self.wait(run["id"], timeout=timeout)
            except subprocess.TimeoutExpired:
                done = {"status": "running"}
        if done["status"] == "running":
            try:
                self.cancel(actor, run["id"])  # 超时：停掉这次测试运行
            except BurrowlError:
                pass  # 恰好已经结束
        output = "".join(self.output(run["id"])["lines"])
        expected = run["data"]["agent_actor"]
        finished = done["status"] not in ("running", "cancelling")
        ran = finished and done["status"] == "done"
        last = next((ln.strip() for ln in reversed(output.splitlines()) if ln.strip()), "")
        detail = done["status"] if finished else f"{timeout:.0f} 秒内没有结束"
        if not ran and last:  # 失败时带上 agent 最后一行输出（例如 Claude Code 没登录："Not logged in"）
            detail += f"：{last[:200]}"
        steps.append({"step": "run", "ok": ran, "run_id": run["id"], "detail": detail,
                      "seconds": round(time.monotonic() - t1, 1)})
        steps.append({"step": "identity", "ok": expected in output, "expected": expected,
                      "detail": "输出里有这次运行的身份" if expected in output
                      else "输出里没有这次运行的身份：MCP 可能没有连上，或身份不对",
                      "output_tail": output[-400:]})
        return {"agent": agent, "ok": all(s["ok"] for s in steps), "steps": steps, "run_id": run["id"]}

    def wait(self, run_id: str, timeout: float = 30) -> dict:
        with self._lock:
            proc = self._procs.get(run_id)
        if proc is not None:
            proc.wait(timeout=timeout)
        for _ in range(int(timeout * 20)):  # 等输出线程登记完成
            with self.ws.lock:
                run = self.ws.framework.run(run_id)
            if run["status"] not in ("running", "cancelling"):
                return run
            threading.Event().wait(0.05)
        return self.ws.framework.run(run_id)


def find_candidates(command: str) -> list[str]:
    """本机常见安装位置里找得到的同名可执行文件（设计稿 08 D-39），最新的在前；只用来给人挑，不自动采用。
    Claude 桌面版自带的 Claude Code 在 %LOCALAPPDATA%/Claude-Data/…/claude-code/<版本>/…/claude.exe，路径随版本变。"""
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData/Local")
    roaming = Path(os.environ.get("APPDATA") or home / "AppData/Roaming")
    names = [command, f"{command}.exe", f"{command}.cmd"]
    paths: list[Path] = []
    for folder in (home / ".local/bin", roaming / "npm", local / "Programs" / command):
        paths += [folder / n for n in names]
    if command == "claude":
        paths += list(local.glob("Claude-Data/*/claude-code/*/*/claude.exe"))
    found = []
    for p in paths:
        try:  # 应用执行别名等重解析点读状态会报错：跳过
            if p.is_file():
                found.append((p.stat().st_mtime, str(p)))
        except OSError:
            continue
    found.sort(reverse=True)
    return list(dict.fromkeys(p for _, p in found))
