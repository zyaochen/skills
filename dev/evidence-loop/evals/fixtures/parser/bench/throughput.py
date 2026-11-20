"""确定性吞吐基准：先跑单元测试保证正确，再统计解析固定语料时 src/ 里执行的 Python 行数，
折算成"每百万行解释开销能解析的记录数"。分数越高越好，同一份代码每次结果相同。
"""
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.realpath(os.path.join(ROOT, "src"))
sys.path.insert(0, SRC)

if subprocess.run([sys.executable, os.path.join(ROOT, "tests", "test_kvparse.py")],
                  capture_output=True).returncode != 0:
    sys.exit("单元测试未通过，拒绝计分")

import kvparse  # noqa: E402

CORPUS = "\n".join(f"id={i};name=user{i};city=c{i % 17};score={i * 3 % 101}" for i in range(300))
count = 0


def tracer(frame, event, arg):
    global count
    if os.path.realpath(frame.f_code.co_filename).startswith(SRC):
        if event == "line":
            count += 1
        return tracer
    return None


sys.settrace(tracer)
records = kvparse.parse(CORPUS)
sys.settrace(None)
if len(records) != 300 or records[7]["name"] != "user7":
    sys.exit("解析结果错误")
print(f"records={len(records)}")
print(f"throughput={len(records) * 1_000_000 / count:.1f}")
