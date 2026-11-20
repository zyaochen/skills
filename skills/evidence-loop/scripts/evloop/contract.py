"""契约目录：密封的 contract.json、只追加的 attempts.jsonl、raw/ 原始输出、.lock 互斥锁。

contract.json 在每次保存时写入 agreement_sha（除 agreement_sha / approved 外所有字段的哈希），
每次加载都会重新计算；手工改动约定会被识别并拒绝——变更约定必须走 init --renew。
"""
import json
import os
import sys

from .util import (INVALID, PROG, SCHEMA_VERSION, append_line, atomic_write_json,
                   fail, file_lock, sha256_json)

UNSEALED = {"agreement_sha", "approved"}


def agreement_sha(contract):
    return sha256_json({k: v for k, v in contract.items() if k not in UNSEALED})


class Home:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.contract_path = os.path.join(self.path, "contract.json")
        self.attempts_path = os.path.join(self.path, "attempts.jsonl")
        self.raw = os.path.join(self.path, "raw")
        self.lock_path = os.path.join(self.path, ".lock")

    # ------------------------------------------------------------ 目录
    def ensure(self):
        os.makedirs(self.raw, exist_ok=True)

    def exists(self):
        return os.path.exists(self.contract_path)

    def lock(self):
        return file_lock(self.lock_path)

    def raw_path(self, name):
        self.ensure()
        return os.path.join(self.raw, name)

    def file(self, name):
        return os.path.join(self.path, name)

    # ------------------------------------------------------------ 契约
    def read_raw(self):
        try:
            with open(self.contract_path, encoding="utf-8") as f:
                return json.load(f)
        except ValueError as e:
            fail(f"contract.json 已损坏：{e}", INVALID)

    def load(self):
        if not self.exists():
            fail(f"{self.contract_path} 不存在；先运行 init")
        c = self.read_raw()
        if not isinstance(c, dict):
            fail("contract.json 不是 JSON 对象", INVALID)
        version = c.get("schema_version", SCHEMA_VERSION)
        if version > SCHEMA_VERSION:
            fail(f"契约格式版本 {version} 比当前工具支持的 {SCHEMA_VERSION} 新；请升级 {PROG}")
        if c.get("agreement_sha") != agreement_sha(c):
            fail("contract.json 在 init 之后被改动过；约定变化需要重新澄清并 init --renew", INVALID)
        return c

    def save(self, contract):
        self.ensure()
        contract.setdefault("schema_version", SCHEMA_VERSION)
        contract["agreement_sha"] = agreement_sha(contract)
        atomic_write_json(self.contract_path, contract)

    # ------------------------------------------------------------ 记录
    def attempts(self):
        """读取全部记录。末行残缺（写入中断）时忽略并告警，中间行损坏则拒绝。"""
        if not os.path.exists(self.attempts_path):
            return []
        with open(self.attempts_path, encoding="utf-8", errors="replace") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        rows = []
        for i, line in enumerate(lines):
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or "n" not in row:
                    raise ValueError("缺少 n 字段")
            except ValueError as e:
                if i == len(lines) - 1:
                    print(f"{PROG}: 忽略 attempts.jsonl 末尾的残缺记录（{e}）", file=sys.stderr)
                    break
                fail(f"attempts.jsonl 第 {i + 1} 行损坏：{e}", INVALID)
            rows.append(row)
        return rows

    def next_n(self):
        return 1 + max([r["n"] for r in self.attempts()] + [0])

    def log(self, record):
        self.ensure()
        self._drop_torn_tail()
        append_line(self.attempts_path, json.dumps(record, ensure_ascii=False))

    def _drop_torn_tail(self):
        """上次写入若被中断，文件会以不完整的一行结尾；追加前截掉它，免得变成中间的坏行。"""
        if not os.path.exists(self.attempts_path) or not os.path.getsize(self.attempts_path):
            return
        with open(self.attempts_path, "rb+") as f:
            data = f.read()
            if data.endswith(b"\n"):
                return
            cut = data.rfind(b"\n") + 1
            f.seek(cut)
            f.truncate()
        print(f"{PROG}: 已截掉 attempts.jsonl 末尾被中断的半行记录", file=sys.stderr)
