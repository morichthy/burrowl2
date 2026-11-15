"""生成一份演示数据：一次泵站排查。用法：uv run python tools/seed_demo.py <数据目录>

覆盖：原件（巡检记录、文献）、读取记录、事实记录、人与 AI 的判断、约束、实体、综合页、
AI 推断的边、术语连接的三档、佐证与自由标签关系，一次撤回造成的"输入已变化"，
以及一条判断的更正版本与原件的新版本（设计稿 10：版本 @n、关系、坐标）。
"""
import sys

from burrowl.core.actor import Actor
from burrowl.services.workspace import Workspace

ws = Workspace(sys.argv[1])
human = Actor("human:workbench", "human", "ses_01JC00000000000000000DEMO1")
ai = Actor("ai:demo", "ai", "ses_01JC00000000000000000DEMO2")

pump = ws.frameworks.entity_upsert(human, kind="device", name="2号泵")
valve = ws.frameworks.entity_upsert(human, kind="device", name="V-301")
log = ws.artifacts.register(human, kind="log", source_class="local", title="2号泵巡检记录 11-03",
                            text="""# 2号泵巡检记录 11-03

2号泵出口压力 0.82 MPa，波动 ±0.05 MPa。

入口阀 V-301 开度 60%。

| 时间 | 压力 MPa |
|---|---|
| 10:00 | 0.82 |
| 10:05 | 0.87 |
""")
paper = ws.artifacts.register(human, kind="literature", source_class="external", external_tier="peer_reviewed",
                              title="离心泵气蚀与压力脉动",
                              text="离心泵入口压力不足时容易发生气蚀，表现为出口压力脉动增大并伴随噪声。")
rd = ws.artifacts.read(ai, log["id"], "seg:1")["read"]
ev = ws.capture.log(ai, "measure.pressure", output="0.87 MPa", conditions={"time": "10:05", "gauge": "PG-12"},
                    objects=["2号泵"])
rec = ws.artifacts.promote(ai, event_id=ev["id"], method="出口压力表 PG-12 读数")
c = ws.judgments.write(human, kind="constraint", subkind="action", text="检修完成前不要调整 V-301 开度",
                       objects=[valve["id"]])
j1 = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力波动 ±0.05 MPa，10:05 升到 0.87 MPa",
                        cites=[rd["id"], rec["id"]], objects=[pump["id"]])
j2 = ws.judgments.write(ai, kind="conclusion", text="2号泵的压力波动可能来自入口气蚀（V-301 开度 60% 时入口压力偏低）",
                        cites=[j1["id"], paper["id"]], objects=[pump["id"], valve["id"]])
j3 = ws.judgments.write(ai, kind="conclusion", text="2号泵压力正常，不需要处理", cites=[rd["id"]], objects=[pump["id"]])
ws.frameworks.edge_add(ai, rel="may_contradict", src_id=j2["id"], dst_id=j3["id"], reason="一个说可能气蚀，一个说正常")
page = ws.frameworks.page_write(ai, type="synthesis", title="2号泵压力波动排查", subject_id=pump["id"],
                                summary="2号泵出口压力波动的证据、可能原因与未解决部分",
                                body=f"""## 问题
2号泵出口压力波动的原因。

## 当前结论
- 压力波动 ±0.05 MPa（亲自执行）：[[{j1['id']}]]
- 可能原因是入口气蚀（混合来源，未复核）：[[{j2['id']}]]

## 可能有误的地方
- [[{j3['id']}]] 认为压力正常，与上一条矛盾，尚未裁决。
""", inputs=[j1["id"], j2["id"], j3["id"]])
ws.versions.change_state(human, j3["id"], "withdraw", "10:05 的 0.87 MPa 已超过 0.85 MPa 上限，不能算正常")
# 本地实证佐证文献里的说法；自由标签关系（设计稿 10 D-08、D-09）
claim = ws.judgments.write(ai, kind="conclusion", text="离心泵入口压力不足时出口压力脉动增大", cites=[paper["id"]],
                           external_author="文献作者", conditions="离心泵；入口压力不足")
ws.judgments.write(ai, kind="conclusion", text="2号泵在 V-301 开度 60% 时出口压力脉动增大到 ±0.05 MPa",
                   cites=[rd["id"]], objects=[pump["id"]],
                   relations=[{"rel": "supports", "target": claim["id"]},
                              {"rel": "relates", "label": "可能导致", "target": j2["id"]}])
# 一条判断的更正版本、原件的新版本：引用旧版的判断带"依据有变化"
ws.versions.correct(human, j1["id"], reason="复核压力表读数", text="2号泵出口压力波动 ±0.05 MPa，10:05 升到 0.88 MPa")
ws.artifacts.register(human, kind="log", source_class="local", version_of=log["id"],
                      title="2号泵巡检记录 11-03（校正）",
                      text="# 2号泵巡检记录 11-03\n\n2号泵出口压力 0.83 MPa，波动 ±0.05 MPa。\n")
ws.linking.link_term(ai, term="2号", source_id=log["id"], excerpt="2号泵出口压力")
ws.frameworks.entity_upsert(human, kind="device", name="2号泵备用")
ws.linking.link_term(ai, term="2号", source_id=log["id"], excerpt="2号泵出口压力")
print("ok", {"log": log["id"], "page": page["id"], "constraint": c["id"]})
