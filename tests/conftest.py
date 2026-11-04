import pytest

from burrowl.core.actor import Actor
from burrowl.services.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    w = Workspace(tmp_path / "data")
    yield w
    w.close()


@pytest.fixture
def human():
    return Actor("human:tester", "human", "ses_01JC0000000000000000000001")


@pytest.fixture
def ai():
    return Actor("ai:test", "ai", "ses_01JC0000000000000000000002")


PUMP_LOG = """# 2号泵巡检记录

2号泵出口压力 0.82 MPa，波动 ±0.05 MPa。

入口阀 V-301 开度 60%。

| 时间 | 压力 MPa |
|---|---|
| 10:00 | 0.82 |
| 10:05 | 0.87 |
"""


@pytest.fixture
def pump_log(ws, human):
    return ws.artifacts.register(human, kind="log", source_class="local", text=PUMP_LOG, title="2号泵巡检")
