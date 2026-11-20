"""确定性延迟基准：统计每次查询在 src/ 里执行的 Python 行数，按固定系数折算成毫秒。

用行数而不是墙钟时间，是为了让同一份代码每次跑出完全相同的分数（噪声为 0）。
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.realpath(os.path.join(ROOT, "src"))
sys.path.insert(0, SRC)

import lookup  # noqa: E402

LINES_PER_MS = 16.46
ORDERS = [{"id": (i * 7919) % 1000, "amount": i} for i in range(1000)]
QUERIES = [(q * 37) % 1000 for q in range(400)]

count = 0


def tracer(frame, event, arg):
    global count
    if os.path.realpath(frame.f_code.co_filename).startswith(SRC):
        if event == "line":
            count += 1
        return tracer
    return None


index = lookup.build_index(ORDERS)
costs = []
for q in QUERIES:
    count = 0
    sys.settrace(tracer)
    hit = lookup.find(index, q)
    sys.settrace(None)
    if hit is None or hit["id"] != q:
        sys.exit(f"查询 {q} 结果错误：{hit}")
    costs.append(count)
costs.sort()
p99 = costs[int(len(costs) * 0.99) - 1] / LINES_PER_MS
print(f"queries={len(costs)}")
print(f"p99={p99:.1f}")
