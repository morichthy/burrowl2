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
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import new_id

# 新工作区内置两条可编辑的启动配置。既有工作区继续使用已保存的命令。
AGENT_CLI_PRESETS = {
    "claude": ["claude", "-p", "{prompt}", "--mcp-config", "{mcp_config}", "--output-format", "text"],
    # 只预批连接探测；巡检及复核需要的工具权限由使用者按配置设置。
    "codex": ["codex", "exec", "--skip-git-repo-check", "-c", "{codex_mcp_config}",
              "-c", "mcp_servers.burrowl.tools.system_status.approval_mode='approve'", "{prompt}"],
}
AgentCliType = Literal["codex", "claude", "custom"]

# 工作台在后台运行。版本探测和任务启动均通过管道读取输出，无需分配 Windows 控制台。
_AGENT_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_MODEL_TIMEOUT = 180

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
            out.append({"name": name, "command": spec["command"], "cli_type": spec.get("cli_type"),
                        "executable": exe, "default_executable": default,
                        "resolved": resolved, "available": resolved is not None,
                        "found": [p for p in find_candidates(Path(default).name) if p != resolved]})
        return out

    def save_command(self, actor: Actor, *, agent: str, command: list[str],
                     cli_type: AgentCliType | None = None, previous: str | None = None) -> dict:
        """新增或替换启动模板。首项是程序，其余项原样作为独立参数传入。
        previous 是改名前的名称：配置移到新名称下，巡检、复核和大模型的引用一并更新。"""
        actor.require_human("配置 agent 命令")
        agent = agent.strip()
        previous = (previous or "").strip() or None
        if previous == agent:
            previous = None
        if previous is not None:
            if previous not in self.ws.config["agents"]:
                raise BurrowlError("NOT_FOUND", "没有配置这个 agent",
                                   {"agent": previous, "known": list(self.ws.config["agents"])})
            if agent in self.ws.config["agents"]:
                raise BurrowlError("CONFLICT", "这个名称已被其他 Agent 配置使用", {"agent": agent})
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
        spec = agents.get(previous or agent, {})
        updated = {**spec, "command": command}
        # 旧调用方可以只保存命令；显式选择“自定义”时，即使参数等于预设也保留选择。
        if cli_type is not None:
            updated["cli_type"] = cli_type
        if previous is not None:
            # 改名保持原有顺序；引用旧名称的巡检角色改为新名称。
            renamed = {(agent if name == previous else name): (updated if name == previous else value)
                       for name, value in agents.items()}
            roles = self._references(previous)
            changes = {f"agents.{previous}": {"from": spec, "to": None},
                       f"agents.{agent}": {"from": None, "to": updated},
                       **{f"inspection.{role}": {"from": previous, "to": agent} for role in roles}}
            config = {"agents": renamed}
            if roles:
                config["inspection"] = {role: agent for role in roles}
            if self.ws.config.get("models", {}).get("llm_agent") == previous:
                config["models"] = {"llm_agent": agent}
                changes["models.llm_agent"] = {"from": previous, "to": agent}
            self.ws.save_config(config, replace=("agents",))
            self.ws.capture.log(actor, "settings.set", input={"changes": changes})
            return next(a for a in self.agents() if a["name"] == agent)
        changes = {f"agents.{agent}.{key}": {"from": spec.get(key), "to": updated[key]}
                   for key in ("command", "cli_type") if spec.get(key) != updated.get(key)}
        if changes:
            self.ws.save_config({"agents": {**agents, agent: updated}})
            self.ws.capture.log(actor, "settings.set", input={"changes": changes})
        return next(a for a in self.agents() if a["name"] == agent)

    def _references(self, agent: str) -> list[str]:
        """引用这条配置的巡检角色（inspector / reviewer）。"""
        inspection = self.ws.config.get("inspection", {})
        return [role for role in ("inspector", "reviewer") if inspection.get(role) == agent]

    def delete(self, actor: Actor, *, agent: str) -> dict:
        """删除一条 Agent 配置。巡检、复核或大模型仍在使用时拒绝。已有运行记录保留。"""
        actor.require_human("删除 agent 配置")
        agents = self.ws.config["agents"]
        if agent not in agents:
            raise BurrowlError("NOT_FOUND", "没有配置这个 agent", {"agent": agent, "known": list(agents)})
        models = self.ws.config.get("models", {})
        if models.get("llm_agent") == agent and models.get("llm") == "agent":
            raise BurrowlError("CONFLICT", "大模型正在使用这条配置，请先在「模型与引擎」中改选", {"agent": agent})
        roles = self._references(agent)
        if roles:
            names = "、".join({"inspector": "巡检员", "reviewer": "复核员"}[r] for r in roles)
            raise BurrowlError("CONFLICT", f"{names}正在使用这条配置，请先在巡检设置中改选其他 Agent",
                               {"agent": agent, "roles": roles})
        removed = agents[agent]
        config = {"agents": {k: v for k, v in agents.items() if k != agent}}
        changes = {f"agents.{agent}": {"from": removed, "to": None}}
        if models.get("llm_agent") == agent:
            config["models"] = {"llm_agent": ""}
            changes["models.llm_agent"] = {"from": agent, "to": ""}
        self.ws.save_config(config, replace=("agents",))
        self.ws.capture.log(actor, "settings.set",
                            input={"changes": changes})
        return {"agent": agent, "deleted": True}

    @staticmethod
    def model_answer(spec: dict, prompt: str, png: bytes | None = None) -> str:
        """在临时目录执行一次问答，复用已保存的命令，不注入 Burrowl 的 MCP 身份。"""
        exe = shutil.which(spec["command"][0])
        if exe is None:
            raise BurrowlError("AGENT_NOT_FOUND", f"找不到命令 {spec['command'][0]}，请检查「Agent」设置")
        args = spec["command"][1:]
        # 配置类型可以来自创建时的模板。专用选项必须与实际运行的程序匹配。
        executable = Path(exe).stem.lower()
        codex = executable == "codex" and args[:1] == ["exec"]
        claude = executable == "claude"
        codex_stdin = codex and [part for part in args if "{prompt}" in part] == ["{prompt}"]
        # Windows 拒绝终止后代时，清理失败不能盖过原来的调用错误。
        with tempfile.TemporaryDirectory(prefix="burrowl-model-", ignore_cleanup_errors=True) as temp:
            folder = Path(temp)
            if png is not None:
                (folder / "input.png").write_bytes(png)
            if not codex_stdin:
                (folder / "task.txt").write_text(prompt, encoding="utf-8")
            (folder / "mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")
            # 识别文本来自原件，只写入 UTF-8 文件。Windows 的命令转发脚本也只收到固定参数。
            text = "Read task.txt in the current directory and follow the task. Return only the answer."
            if png is not None and not codex:
                text += " Use input.png in the current directory as the source image."
            # Codex 即使不启动禁用的服务，也要求服务配置声明一种传输方式。
            replacements = {
                "{prompt}": "-" if codex_stdin else text,
                "{mcp_config}": "mcp.json",
                "{codex_mcp_config}": "mcp_servers.burrowl={command='burrowl-model-disabled',enabled=false}",
            }
            command = [exe, *(re.sub(r"\{(?:prompt|mcp_config|codex_mcp_config)\}",
                                     lambda m: replacements[m[0]], part) for part in args)]
            if codex:
                # --image 可接收多项，后面紧跟另一个选项，避免把位置参数当成图片。
                flags = ["--image", "input.png"] if png is not None else []
                flags += ["--output-last-message", "answer.txt", "--sandbox", "read-only", "--ephemeral"]
                if "--skip-git-repo-check" not in args:
                    flags += ["--skip-git-repo-check"]
                command[2:2] = flags
            if claude:
                command[1:1] = ["--tools=Read", "--strict-mcp-config", "--no-session-persistence"]
                if not any("{mcp_config}" in part for part in args):
                    command[1:1] = ["--mcp-config=mcp.json"]
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith("BURROWL_")}
            env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
            try:
                # 用文件重定向。Windows 的 .cmd 转发脚本启动的子进程可能持有输出管道，导致超时后仍在等 EOF。
                with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as target:
                    if codex_stdin:
                        source.write(prompt.encode("utf-8"))
                        source.seek(0)
                    with subprocess.Popen(
                        command, cwd=folder, env=env, stdin=source if codex_stdin else subprocess.DEVNULL,
                        stdout=target, stderr=subprocess.DEVNULL, creationflags=_AGENT_CREATION_FLAGS,
                        start_new_session=os.name != "nt",
                    ) as proc:
                        try:
                            proc.wait(timeout=_MODEL_TIMEOUT)
                        except subprocess.TimeoutExpired:
                            AgentService._stop_model_process(proc)
                            raise
                    if proc.returncode:
                        raise BurrowlError("MODEL_ERROR",
                                           f"Agent CLI 调用失败（退出码 {proc.returncode}），请检查登录和启动参数")
                    target.seek(0)
                    answer = ((folder / "answer.txt").read_text(encoding="utf-8") if codex
                              else target.read().decode("utf-8", errors="replace"))
            except subprocess.TimeoutExpired as exc:
                raise BurrowlError("MODEL_ERROR", f"Agent CLI 在 {_MODEL_TIMEOUT} 秒内没有返回回答") from exc
            except (OSError, UnicodeError) as exc:
                raise BurrowlError("MODEL_ERROR", "无法运行 Agent CLI 或读取它的回答") from exc
        if not answer.strip():
            raise BurrowlError("MODEL_ERROR", "Agent CLI 没有返回回答")
        return answer.strip()

    @staticmethod
    def _stop_model_process(proc: subprocess.Popen) -> None:
        """先终止启动器及其后代，再关闭临时文件。"""
        if os.name == "nt":
            try:
                subprocess.run(["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=_AGENT_CREATION_FLAGS, timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.kill()  # 进程已结束时为无操作；清理整棵树失败时至少结束启动器。

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
        # Codex 接收 TOML 覆盖项，MCP 子进程从本次运行继承身份、会话与数据目录。
        # 普通路径用 TOML 单引号，避免 Windows 的 codex.cmd 转发参数时剥掉双引号。
        python = Path(sys.executable).as_posix()
        quoted_python = f"'{python}'" if "'" not in python else json.dumps(python, ensure_ascii=False)
        codex_config = (f"mcp_servers.burrowl={{command={quoted_python},args=['-m','burrowl.interfaces.cli','mcp'],"
                        "env_vars=['BURROWL_ACTOR_ID','BURROWL_SESSION','BURROWL_DATA']}")
        args = spec["command"][1:]
        # npm 的 Windows .cmd 转发参数时会在换行处截断。自定义 CLI 也可能运行 Codex。
        # Codex exec 的独立任务参数可换成 "-"，其他 CLI 及内嵌占位符仍按原模板传参。
        codex_stdin = (spec.get("cli_type") == "codex" or Path(exe).stem.lower() == "codex") and (
            args[:1] == ["exec"] and [arg for arg in args if "{prompt}" in arg] == ["{prompt}"])
        replacements = {"{prompt}": "-" if codex_stdin else text, "{mcp_config}": str(mcp_path),
                        "{codex_mcp_config}": codex_config}
        placeholders = r"\{(?:prompt|mcp_config|codex_mcp_config)\}"
        command = [exe, *(re.sub(placeholders, lambda match: replacements[match[0]], part)
                          for part in args)]
        workdir = Path(cwd).expanduser() if cwd else self.ws.root
        self.ws.framework.add_run(run_id, agent, session_id, {
            "prompt": prompt, "command": spec["command"], "cwd": str(workdir), "started_by": actor.id,
            "agent_actor": agent_actor, "preamble": preamble,
            # 在子进程启动前登记身份，首个 MCP 请求也能识别巡检会话。
            **({"inspection_id": inspection_id, "inspection_role": inspection_role} if inspection_id else {})})
        self.ws.capture.log(actor, "agent.start", input={"run_id": run_id, "agent": agent, "prompt": prompt})
        # 子进程输出统一为 UTF-8（Windows 默认是 GBK）
        env = {**os.environ, "BURROWL_ACTOR_ID": agent_actor, "BURROWL_SESSION": session_id,
               "BURROWL_DATA": str(self.ws.root), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        # npm 的 Codex 转发脚本需要继承标准输入管道。独立写入，长提示和输出可同时传输。
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.PIPE if codex_stdin else subprocess.DEVNULL,
                                cwd=workdir, env=env, text=True, encoding="utf-8", errors="replace", bufsize=1,
                                creationflags=_AGENT_CREATION_FLAGS)
        with self._lock:
            self._buffers[run_id] = []
            self._procs[run_id] = proc
        threading.Thread(target=self._pump, args=(run_id, proc, run_dir), daemon=True).start()
        if proc.stdin is not None:
            threading.Thread(target=self._send_prompt, args=(proc.stdin, text), daemon=True).start()
        return self.ws.framework.run(run_id)

    @staticmethod
    def _send_prompt(stdin, text: str) -> None:
        try:
            with stdin:
                # 直接写 UTF-8 字节，保留原有换行。关闭管道后 Codex 读到 EOF。
                stdin.buffer.write(text.encode("utf-8"))
        except BrokenPipeError:
            # CLI 提前退出时，退出码和诊断由输出线程记录。
            pass

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
                                  errors="replace", timeout=30, stdin=subprocess.DEVNULL,
                                  creationflags=_AGENT_CREATION_FLAGS)
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
