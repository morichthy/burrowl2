"""外部阅读引擎（设计稿 03 D-13）：ONLYOFFICE Docs 的只读查看。

引擎由用户自己安装运行（Docker 或官方安装包），burrowl 不打包、不启动它。工作台向浏览器给出一份
签名的编辑器配置（mode=view，不能编辑、不能批注），引擎凭其中一次性的取文件地址来 burrowl 取原件：
- 取文件地址带一次性令牌，只对一份原件、10 分钟内有效，只读；令牌只存在工作台进程内存里，重启即失效；
- 地址的主机由设置 viewer.onlyoffice_burrowl_url 决定（引擎在 Docker 里时通常是 http://host.docker.internal:端口），
  不填时用浏览器访问工作台的地址；
- 配置用 viewer.onlyoffice_secret（与引擎的 JWT 密钥相同）按 HS256 签名；密钥只在服务端，不发给浏览器以外的地方。
签名只用标准库，不增加依赖。
"""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.error
import urllib.request

from ..core.errors import BurrowlError

TICKET_TTL = 600  # 秒
DOCUMENT_TYPE = {"docx": "word", "xlsx": "cell", "pptx": "slide", "pdf": "pdf"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_jwt(payload: dict, secret: str) -> str:
    """HS256 JWT（ONLYOFFICE 要求的签名方式）。"""
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    sig = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(sig)}"


class Tickets:
    """一次性取文件令牌：ticket → (数据目录名, 原件 ID, 过期时间)。"""

    def __init__(self):
        self._items: dict[str, tuple[str | None, str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, db: str | None, artifact_id: str) -> str:
        ticket = secrets.token_urlsafe(24)
        now = time.time()
        with self._lock:
            self._items = {k: v for k, v in self._items.items() if v[2] > now}
            self._items[ticket] = (db, artifact_id, now + TICKET_TTL)
        return ticket

    def resolve(self, ticket: str) -> tuple[str | None, str]:
        with self._lock:
            item = self._items.get(ticket)
        if item is None or item[2] < time.time():
            raise BurrowlError("FORBIDDEN", "取文件令牌无效或已过期")
        return item[0], item[1]


def settings_of(ws) -> dict:
    v = ws.config.get("viewer", {})
    return {"url": (v.get("onlyoffice_url") or "").rstrip("/"), "secret": v.get("onlyoffice_secret") or "",
            "burrowl_url": (v.get("onlyoffice_burrowl_url") or "").rstrip("/")}


def onlyoffice_config(ws, art: dict, fmt: str, *, file_url: str, lang: str = "zh") -> dict:
    """浏览器用来打开 ONLYOFFICE 只读查看器的配置：{api, config}。"""
    s = settings_of(ws)
    if not s["url"]:
        raise BurrowlError("ENGINE_UNAVAILABLE", "还没有在设置里填写 ONLYOFFICE 的地址")
    doc_type = DOCUMENT_TYPE.get(fmt)
    if doc_type is None:
        raise BurrowlError("INVALID_ARGUMENT", "ONLYOFFICE 只用于 Word、Excel、PPT 与 PDF", {"format": fmt})
    d = art["data"]
    config = {
        "document": {
            "fileType": (d.get("suffix") or f".{fmt}").lstrip("."),
            "key": art["sha256"][:40],  # 原件不可变：内容相同的原件共用缓存
            "title": d.get("filename") or d.get("title") or art["id"],
            "url": file_url,
            "permissions": {"edit": False, "comment": False, "review": False, "fillForms": False,
                            "modifyFilter": False, "download": True, "print": True, "copy": True},
        },
        "documentType": doc_type,
        "editorConfig": {"mode": "view", "lang": lang,
                         "customization": {"compactHeader": True, "hideRightMenu": True, "toolbarNoTabs": True,
                                           "forcesave": False}},
        "type": "desktop",
        "width": "100%",
        "height": "100%",
    }
    if s["secret"]:
        config["token"] = sign_jwt(config, s["secret"])
    return {"api": f"{s['url']}/web-apps/apps/api/documents/api.js", "config": config}


def check_onlyoffice(url: str, timeout: float = 5.0) -> dict:
    """连接测试：ONLYOFFICE Docs 的 /healthcheck 正常时返回 true。"""
    url = url.rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise BurrowlError("INVALID_ARGUMENT", "地址要以 http:// 或 https:// 开头", {"url": url})
    try:
        with urllib.request.urlopen(f"{url}/healthcheck", timeout=timeout) as r:  # noqa: S310 - 用户填写的引擎地址
            body = r.read(200).decode("utf-8", errors="replace").strip()
        return {"ok": body.lower() == "true", "detail": body or "（空响应）"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "detail": str(getattr(exc, "reason", exc))}
