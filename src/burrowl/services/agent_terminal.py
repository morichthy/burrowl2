"""Agent 的 Windows 伪终端。浏览器只能收发已启动会话的终端字符。"""
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from ..core.errors import BurrowlError

TERMINAL_ARGS = {
    "agy": ["--prompt-interactive", "{prompt}"],
    "claude": ["--mcp-config", "{mcp_config}", "{prompt}"],
    "codex": ["-c", "{codex_mcp_config}", "{prompt}"],
}


def terminal_command(command: list[str]) -> list[str]:
    """已知 npm 启动器直接运行其 Node 入口，避免 CMD 解释任务里的换行和元字符。"""
    exe = Path(command[0])
    if exe.suffix.lower() == ".exe":
        return command
    if exe.suffix.lower() == ".cmd":
        entry = {"codex": "@openai/codex/bin/codex.js",
                 "claude": "@anthropic-ai/claude-code/cli.js"}.get(exe.stem.lower())
        node = shutil.which(str(exe.with_name("node.exe"))) or shutil.which("node.exe")
        if entry and node:
            script = exe.parent / "node_modules" / entry
            if script.is_file():
                return [node, str(script), *command[1:]]
    raise BurrowlError("INVALID_ARGUMENT", "浏览器终端需要原生 .exe 或受支持的 npm 启动器，请检查「Agent」配置")


class AgentTerminal:
    def __init__(self, command: list[str], cwd: Path, env: dict[str, str]):
        if os.name != "nt":
            raise BurrowlError("INVALID_ARGUMENT", "浏览器终端目前支持 Windows 工作台")
        from winpty import PTY, Backend, WinptyError  # noqa: PLC0415 - 仅 Windows 安装

        self._pty_error = WinptyError
        try:
            self._pty = PTY(80, 24, backend=Backend.ConPTY)
            # 首项由 ConPTY 接收，其余项按 Windows argv 规则转义，不经 shell。
            args = " " + subprocess.list2cmdline(command[1:]) if len(command) > 1 else None
            env_block = "\0".join(f"{key}={value}" for key, value in sorted(env.items(), key=lambda kv: kv[0].upper()))
            if not self._pty.spawn(command[0], cmdline=args, cwd=str(cwd), env=env_block + "\0"):
                raise OSError("ConPTY did not start the CLI")
        except (WinptyError, OSError) as exc:
            raise BurrowlError("AGENT_START_FAILED", "无法启动 Agent 浏览器终端，请检查命令和工作目录") from exc

    def chunks(self):
        """连续读输出。进程退出后仍排空缓冲，以保留最后一屏。"""
        while True:
            try:
                chunk = self._pty.read(blocking=False)
            except self._pty_error:
                if self._pty.isalive():
                    raise
                return
            if chunk:
                yield chunk
            elif self._pty.iseof() or not self._pty.isalive():
                return
            else:
                time.sleep(0.04)

    def wait(self) -> int:
        while self._pty.isalive():
            time.sleep(0.04)
        return self._pty.get_exitstatus()

    def input(self, text: str | None, cols: int | None, rows: int | None) -> None:
        try:
            if not self._pty.isalive():
                raise BurrowlError("CONFLICT", "这次会话已经结束")
            if text is not None:
                self._pty.write(text)
            if cols is not None and rows is not None:
                self._pty.set_size(cols, rows)
        except self._pty_error as exc:
            raise BurrowlError("CONFLICT", "终端已断开，无法发送输入") from exc

    def stop(self) -> None:
        if self._pty.isalive():
            stop_windows_tree(self._pty.pid)
            if self._pty.isalive():
                try:
                    os.kill(self._pty.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass


def stop_windows_tree(pid: int) -> None:
    """Windows 的 CLI 启动器可能还有实际运行 CLI 的后代进程。"""
    try:
        subprocess.run(["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass
