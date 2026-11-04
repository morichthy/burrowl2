"""导出与导入（DESIGN §3.4）：大版本升级可以只靠它完成，不依赖内部表结构。

导出目录：
    manifest.json        格式版本、程序版本、每个文件的行数与 sha256
    ledger/<表>.jsonl    账本各表，一行一条
    framework/<表>.jsonl 框架各表
    blobs/               受管原件的内容
    vault/<slug>.md      框架页的当前版本，Markdown + YAML frontmatter（与 Obsidian 兼容）
"""
import json
import shutil
from pathlib import Path

from .. import FORMAT_VERSION, __version__
from ..core.clock import now
from ..core.errors import BurrowlError
from ..core.hashing import sha256_file
from ..store.db import transaction

LEDGER_TABLES = ("artifacts", "events", "records", "reads", "judgments", "links", "entry_objects")
FRAMEWORK_TABLES = ("entities", "aliases", "pages", "page_versions", "edges", "derivation_inputs", "decisions",
                    "agent_runs")


class Portability:
    def __init__(self, ws):
        self.ws = ws

    def export(self, target: str) -> dict:
        out = Path(target).expanduser().resolve()
        if out.exists() and any(out.iterdir()):
            raise BurrowlError("CONFLICT", "导出目录必须为空", {"path": str(out)})
        files: dict[str, dict] = {}
        for folder, conn, tables in (("ledger", self.ws.ledger_db, LEDGER_TABLES),
                                     ("framework", self.ws.framework_db, FRAMEWORK_TABLES)):
            (out / folder).mkdir(parents=True, exist_ok=True)
            for table in tables:
                path = out / folder / f"{table}.jsonl"
                count = 0
                with path.open("w", encoding="utf-8", newline="\n") as f:
                    for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                        f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
                        count += 1
                files[f"{folder}/{table}.jsonl"] = {"rows": count, "sha256": sha256_file(path)}
        if self.ws.blobs.root.exists():
            shutil.copytree(self.ws.blobs.root, out / "blobs")
        vault = out / "vault"
        vault.mkdir()
        for page in self.ws.framework.pages():
            view = self.ws.frameworks.page_get(page["id"])
            front = {"id": page["id"], "type": page["type"], "title": page["title"], "version": view["version"],
                     "review": page["review"], "freshness": page["freshness"], "subject": page["subject_id"],
                     "inputs": view["inputs"]}
            yaml = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items())
            (vault / f"{page['slug']}.md").write_text(f"---\n{yaml}\n---\n\n{view['body']}\n", encoding="utf-8")
        manifest = {"format": "burrowl-export", "format_version": FORMAT_VERSION, "program_version": __version__,
                    "exported_at": now(), "files": files}
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def import_(self, source: str) -> dict:
        """导入到空的工作区。旧格式版本的导出必须仍可导入（只增不改）。"""
        src = Path(source).expanduser().resolve()
        manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("format") != "burrowl-export":
            raise BurrowlError("INVALID_ARGUMENT", "不是 burrowl 导出目录", {"path": str(src)})
        if manifest["format_version"] > FORMAT_VERSION:
            raise BurrowlError("CONFLICT", "导出来自更新的版本，请先升级程序",
                               {"format_version": manifest["format_version"]})
        if self.ws.ledger.query("SELECT id FROM artifacts LIMIT 1") or self.ws.ledger.query(
                "SELECT id FROM judgments LIMIT 1"):
            raise BurrowlError("CONFLICT", "只能导入到空的工作区")
        counts = {}
        for folder, conn, tables in (("ledger", self.ws.ledger_db, LEDGER_TABLES),
                                     ("framework", self.ws.framework_db, FRAMEWORK_TABLES)):
            with transaction(conn):
                for table in tables:
                    path = src / folder / f"{table}.jsonl"
                    if not path.exists():
                        continue
                    columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
                    n = 0
                    for line in path.read_text(encoding="utf-8").splitlines():
                        item = {k: v for k, v in json.loads(line).items() if k in columns}
                        conn.execute(f"INSERT INTO {table} ({','.join(item)}) VALUES ({','.join('?' * len(item))})",
                                     list(item.values()))
                        n += 1
                    counts[f"{folder}/{table}"] = n
        if (src / "blobs").exists():
            shutil.copytree(src / "blobs", self.ws.blobs.root, dirs_exist_ok=True)
        counts["index"] = self.ws.rebuild_index()
        return counts
