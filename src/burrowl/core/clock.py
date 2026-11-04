from datetime import UTC, datetime


def now() -> str:
    """ISO 8601 UTC，毫秒精度；所有 created_at 统一用它。"""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
