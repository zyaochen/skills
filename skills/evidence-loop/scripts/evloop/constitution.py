"""项目宪法：跨任务长期生效的规则，init 时合并进契约并按哈希封存。

  {"frozen":    ["tests/golden"],          # 每次任务都冻结的路径
   "generated": ["build"],                 # 约定命令会写入的运行产物目录
   "guard_cmd": "make lint",               # 每次尝试前必须通过的底线检查
   "fast_cmd":  "make unit",               # 默认的快速预检（init --fast-cmd 可覆盖）
   "budget":    {"default_minutes": 60,    # 优化场景未给 --budget-minutes 时的默认值
                 "max_minutes": 240,       # 任何场景的预算上限
                 "reserve_minutes": 10,    # 预留给最终验证与交付的尾段
                 "max_attempts": 40,       # 未给 --max-attempts 时的默认尝试次数上限
                 "token_budget": 2000000}} # 未给 --token-budget 时的默认 token 上限
"""
import json
import os

from .util import CONSTITUTION, fail, norm, sha256_file

TOP_KEYS = {"frozen", "guard_cmd", "fast_cmd", "budget", "generated"}
BUDGET_KEYS = {"default_minutes", "max_minutes", "reserve_minutes", "max_attempts", "token_budget"}


def _validate(law):
    if not isinstance(law, dict):
        fail("宪法必须是 JSON 对象")
    budget = law.get("budget", {})
    if not isinstance(budget, dict):
        fail("宪法的 budget 必须是对象")
    unknown = set(law) - TOP_KEYS
    unknown |= {f"budget.{k}" for k in set(budget) - BUDGET_KEYS}
    if unknown:
        fail(f"宪法含有未知字段：{sorted(unknown)}")
    for key in ("frozen", "generated"):
        value = law.get(key, [])
        if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
            fail(f"宪法的 {key} 必须是非空字符串组成的列表")
    for key in ("guard_cmd", "fast_cmd"):
        cmd = law.get(key)
        if cmd is not None and (not isinstance(cmd, str) or not cmd.strip()):
            fail(f"宪法的 {key} 必须是非空字符串")
    for key, value in budget.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            fail(f"宪法的 budget.{key} 必须是非负数")
        if key in ("max_attempts", "token_budget") and (value != int(value) or value < 1):
            fail(f"宪法的 budget.{key} 必须是正整数")
    return law


def load(repo, rel=None):
    """返回 (宪法, 相对路径)。未显式指定且默认文件不存在时返回 (None, None)。"""
    path = os.path.join(repo, rel or CONSTITUTION)
    if not os.path.isfile(path):
        if rel:
            fail(f"宪法文件不存在：{rel}")
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            law = json.load(f)
    except ValueError as e:
        fail(f"宪法不是合法的 JSON：{e}")
    return _validate(law), norm(os.path.relpath(path, repo))


def seal(repo, rel):
    return {"path": rel, "sha256": sha256_file(os.path.join(repo, rel))}


def drift(contract, root=None):
    """宪法自 init 以来是否被删改：返回 (路径, 'deleted'|'modified') 或 None。"""
    law = contract.get("constitution")
    if not law:
        return None
    path = os.path.join(root or contract["repo"], law["path"])
    if not os.path.isfile(path):
        return law["path"], "deleted"
    if sha256_file(path) != law["sha256"]:
        return law["path"], "modified"
    return None


DRIFT_WORDS = {"deleted": "被删除", "modified": "被修改"}


def drift_text(d):
    return f"宪法 {d[0]} 自 init 以来{DRIFT_WORDS.get(d[1], d[1])}"
