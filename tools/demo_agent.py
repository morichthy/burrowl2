"""演示用的 agent：不调用模型，只演示 agent 通过命令行回到工作区读写（身份由运行器注入，记为 AI）。

真实使用时在 config.json 的 agents 中配置 claude / codex 等命令。
"""
import json
import subprocess
import sys

task = sys.argv[1] if len(sys.argv) > 1 else ""
print("收到任务：", task[:80], flush=True)


def burrowl(op: str, args: dict) -> dict:
    out = subprocess.run([sys.executable, "-m", "burrowl", "call", op, json.dumps(args, ensure_ascii=False)],
                         capture_output=True, text=True, encoding="utf-8")
    return json.loads(out.stdout)


hits = burrowl("search", {"query": "压力", "limit": 3})
print("检索到", len(hits["hits"]), "条；约束", len(hits["constraints"]), "条", flush=True)
for h in hits["hits"]:
    print(" -", h["id"], h["layer"], h["text"][:40].replace("\n", " "), flush=True)
j = burrowl("judgment.write", {"kind": "question", "text": "2号泵入口压力是否低于气蚀余量要求？需要现场测入口压力"})
print("写入提问：", j.get("id"), "作者", j.get("author_id"), flush=True)
