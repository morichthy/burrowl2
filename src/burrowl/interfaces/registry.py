"""操作注册表（沿用 burrowl 的做法）：每个操作写成一个带类型注解的函数，CLI、HTTP、MCP 都从这里生成。

    @op("judgment.write", effect="write")
    def judgment_write(ctx: Ctx, kind: str, text: str, ...) -> dict: ...

effect：
- read / write：三个入口都开放；
- user：只给人在工作台和命令行使用，不出现在 MCP 工具列表中（更正、撤回、复核、术语决定、启动 agent）；
- admin：维护类操作（重建索引、导出、导入），只在命令行和工作台开放。
调用者身份（Ctx.actor）由入口决定，不能由参数指定。
"""
import inspect
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from ..core.actor import Actor
from ..core.errors import BurrowlError

Effect = Literal["read", "write", "user", "admin"]


@dataclass
class Ctx:
    ws: Any            # services.workspace.Workspace
    actor: Actor
    channel: Literal["cli", "http", "mcp"]


@dataclass
class OpSpec:
    name: str
    effect: Effect
    summary: str
    fn: Callable[..., Any]
    model: type[BaseModel]

    @property
    def tool_name(self) -> str:
        return self.name.replace(".", "_")

    def schema(self) -> dict:
        return self.model.model_json_schema()


REGISTRY: dict[str, OpSpec] = {}


def op(name: str, *, effect: Effect = "read") -> Callable[[Callable], Callable]:
    def register(fn: Callable) -> Callable:
        if name in REGISTRY:
            raise ValueError(f"duplicate op: {name}")
        fields: dict[str, Any] = {}
        for p in list(inspect.signature(fn).parameters.values())[1:]:
            annotation = p.annotation if p.annotation is not inspect.Parameter.empty else Any
            fields[p.name] = (annotation, ... if p.default is inspect.Parameter.empty else p.default)
        model = create_model(name.replace(".", "_") + "_input", __config__=ConfigDict(extra="forbid"), **fields)
        summary = " ".join((fn.__doc__ or name).strip().split())
        REGISTRY[name] = OpSpec(name, effect, summary, fn, model)
        return fn
    return register


def load() -> dict[str, OpSpec]:
    """导入内置操作与入口点 burrowl.ops 提供的扩展（导入即注册）。"""
    from . import ops  # noqa: F401, PLC0415 - 导入即注册，放在函数内避免循环导入
    for ep in entry_points(group="burrowl.ops"):
        ep.load()
    return REGISTRY


def jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return value


def call(ctx: Ctx, name: str, arguments: dict | None) -> Any:
    """校验参数后执行；参数错误一次列全。user / admin 操作在 MCP 入口一律拒绝。"""
    spec = load().get(name)
    if spec is None:
        raise BurrowlError("NOT_FOUND", "未知操作", {"op": name})
    if ctx.channel == "mcp" and spec.effect in ("user", "admin"):
        raise BurrowlError("FORBIDDEN", "这个操作只能由人在工作台或命令行执行", {"op": name})
    try:
        parsed = spec.model.model_validate(arguments or {})
    except ValidationError as exc:
        errors = [{"path": "/" + "/".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
        raise BurrowlError("INVALID_ARGUMENT", "参数不符合要求：" + "；".join(f"{e['path']} {e['message']}"
                                                                     for e in errors), {"errors": errors}) from exc
    values = {field: getattr(parsed, field) for field in spec.model.model_fields}
    lock = getattr(ctx.ws, "lock", None) or nullcontext()
    extraction = getattr(ctx.ws, "extraction", None)
    memo = extraction.op_memo() if extraction is not None else nullcontext()
    try:
        # 同一数据目录的操作串行执行（services/workspace.py 的 lock）；操作内复用原件分段（ExtractionService.op_memo）
        with lock, memo:
            return jsonable(spec.fn(ctx, **values))
    except BurrowlError:
        raise
    except Exception as exc:  # noqa: BLE001 - 意外异常统一为 INTERNAL_ERROR，不把堆栈交给调用方
        raise BurrowlError("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", {"op": name}) from exc
