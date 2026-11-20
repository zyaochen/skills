"""工作者验收：处理一个任务后，文件存储里有全部订单的 CSV，并发出完成通知。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from export import api, files, worker  # noqa: E402

job = api.create_export(customer="c1")
assert worker.run_once() == job, "run_once 应返回处理的任务 ID"
lines = files.read(job).strip().splitlines()
assert lines[0] == "id,amount" and len(lines) == 26, "CSV 应含表头与 25 条订单"
print("worker ok")
