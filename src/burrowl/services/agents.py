"""F9 agent 运行器：在工作台直接启动本机 agent CLI（Claude Code、Codex 等）。

- 服务端不直接调用模型 API；AI 工作由 agent 通过 MCP 回到本服务完成（DESIGN §3.1）。
- 每次运行生成独立的 MCP 配置，带上本次运行的身份和会话（BURROWL_ACTOR_ID / BURROWL_SESSION），
  所以 agent 写的内容作者记为这次运行的 AI，过程日志落在这次运行的会话里。
- 输出实时写入内存缓冲与 runs/<编号>/output.log，工作台用 SSE 读取；结束后全部输出登记为对话原件。
"""
import json
import os
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
    "1. 原件只记原文；判断写清对象和条件，并用 cites 引用依据（原件、事实记录、读取记录或判断），不能引用框架页；\n"
    "   判断类型只有 conclusion 结论、process 过程（提问、尝试、停下的路线）、normative 规定；\n"
    "   过程内容不能作为结论的依据；\n"
    "2. 你不能更正或撤回判断；认为某条判断不对时，写一条 opposes 关系的新判断；\n"
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
        out = []
        for name, spec in self.ws.config["agents"].items():
            exe = spec["command"][0]
            out.append({"name": name, "command": spec["command"], "available": shutil.which(exe) is not None})
        return out

    def mcp_config(self, actor_id: str, session_id: str, path: Path) -> Path:
        config = {"mcpServers": {"burrowl": {
            "command": sys.executable, "args": ["-m", "burrowl", "mcp", "--data", str(self.ws.root)],
            "env": {"BURROWL_ACTOR_ID": actor_id, "BURROWL_SESSION": session_id},
        }}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def start(self, actor: Actor, *, agent: str, prompt: str, cwd: str | None = None,
              preamble: bool = True) -> dict:
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
        command = [exe, *(part.replace("{prompt}", text).replace("{mcp_config}", str(mcp_path))
                          for part in spec["command"][1:])]
        workdir = Path(cwd).expanduser() if cwd else self.ws.root
        self.ws.framework.add_run(run_id, agent, session_id, {
            "prompt": prompt, "command": spec["command"], "cwd": str(workdir), "started_by": actor.id,
            "agent_actor": agent_actor})
        self.ws.capture.log(actor, "agent.start", input={"run_id": run_id, "agent": agent, "prompt": prompt})
        # 子进程输出统一为 UTF-8（Windows 默认是 GBK）
        env = {**os.environ, "BURROWL_ACTOR_ID": agent_actor, "BURROWL_SESSION": session_id,
               "BURROWL_DATA": str(self.ws.root), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                cwd=workdir, env=env, text=True, encoding="utf-8", errors="replace", bufsize=1)
        with self._lock:
            self._buffers[run_id] = []
            self._procs[run_id] = proc
        threading.Thread(target=self._pump, args=(run_id, proc, run_dir, actor), daemon=True).start()
        return self.ws.framework.run(run_id)

    def _pump(self, run_id: str, proc: subprocess.Popen, run_dir: Path, actor: Actor) -> None:
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
        self._finish(run_id, code, actor)

    def _finish(self, run_id: str, code: int, actor: Actor) -> None:
        with self.ws.lock:
            run = self.ws.framework.run(run_id)
        output = "".join(self._buffers.get(run_id, []))
        transcript = (f"# agent 运行 {run_id}\n\n- agent：{run['agent']}\n- 命令：{run['data']['command']}\n"
                      f"- 退出码：{code}\n\n## 任务\n\n{run['data']['prompt']}\n\n## 输出\n\n{output}")
        system = Actor("system:agent-runner", "system", run["session_id"])
        with self.ws.lock:  # 输出线程写账本：与请求线程共用连接，需要取数据目录的锁
            art = self.ws.artifacts.register(system, kind="conversation", source_class="inferred", text=transcript,
                                             title=f"agent 运行 {run_id}（{run['agent']}）",
                                             metadata={"run_id": run_id, "exit_code": code})
            status = "done" if code == 0 else ("cancelled" if self.ws.framework.run(run_id)["status"] == "cancelling"
                                                else "failed")
            self.ws.framework.finish_run(run_id, status, {"exit_code": code, "artifact_id": art["id"]})
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

    # ---------- 测试连接（设计稿 07 D-26） ----------
    def test(self, actor: Actor, *, agent: str, timeout: float = 180) -> dict:
        """分三步测一个 agent：① 命令能找到、--version 有输出；② 用一句短提示启动一次，让它经 MCP 调用
        system_status 并原样输出 actor；③ 核对输出里的身份是这次运行的 ai:… 身份。测试运行照常登记为对话原件。
        等待期间放开数据目录的锁：agent 结束时要取锁登记输出。"""
        actor.require_human("测试 agent 连接")
        spec = self.ws.config["agents"].get(agent)
        if spec is None:
            raise BurrowlError("NOT_FOUND", "没有配置这个 agent",
                               {"agent": agent, "known": list(self.ws.config["agents"])})
        steps: list[dict] = []
        exe = shutil.which(spec["command"][0])
        t0 = time.monotonic()
        if exe is None:
            steps.append({"step": "command", "ok": False, "detail": f"找不到命令 {spec['command'][0]}"})
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
            steps.append({"step": "command", "ok": proc.returncode == 0, "detail": version[0] if version else "",
                          "seconds": round(time.monotonic() - t0, 1)})
        except (OSError, subprocess.SubprocessError) as exc:
            steps.append({"step": "command", "ok": False, "detail": f"{type(exc).__name__}: {exc}"})
        if not steps[-1]["ok"]:
            return {"agent": agent, "ok": False, "steps": steps}
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
        steps.append({"step": "run", "ok": finished and done["status"] == "done", "run_id": run["id"],
                      "detail": done["status"] if finished else f"{timeout:.0f} 秒内没有结束",
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

