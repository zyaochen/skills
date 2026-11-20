"""接口验收：create_export 返回任务 ID 并把任务放进队列。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from export import api, queue  # noqa: E402

job = api.create_export(customer="c1")
assert isinstance(job, str) and job, "create_export 必须返回非空任务 ID"
assert queue.size() == 1, "任务必须入队"
print("api ok")
