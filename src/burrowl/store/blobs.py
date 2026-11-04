"""内容寻址的文件存储：blobs/sha256/<前 2 位>/<其余>（与 git-annex、DVC 的做法一致，DESIGN §3.1）。"""
import os
import tempfile
from pathlib import Path

from ..core.hashing import sha256_bytes


class BlobStore:
    def __init__(self, root: Path):
        self.root = root

    def path(self, sha256: str) -> Path:
        return self.root / "sha256" / sha256[:2] / sha256[2:]

    def put(self, data: bytes) -> str:
        """写入并返回 sha256；同内容幂等。先写临时文件再改名，避免半写入。"""
        digest = sha256_bytes(data)
        target = self.path(digest)
        if target.exists():
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return digest

    def get(self, sha256: str) -> bytes:
        return self.path(sha256).read_bytes()

    def has(self, sha256: str) -> bool:
        return self.path(sha256).exists()
