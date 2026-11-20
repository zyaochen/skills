"""共享基础设施：退出码、异常、时间、哈希、原子写、路径规则、文件锁。"""
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import tempfile

# 退出码即裁决：0 接受 / 通过，1 拒绝 / 失败 / 检查点，2 无效，3 前置条件不满足
ACCEPTED, REJECTED, INVALID, PRECONDITION = 0, 1, 2, 3

PROG = "evloop"
STATE_DIR = ".evloop"
RUNS_DIR = STATE_DIR + "/runs"
CONSTITUTION = STATE_DIR + "/constitution.json"
BRANCH_PREFIX = "evloop/"
SCHEMA_VERSION = 1


CODE_NAMES = {ACCEPTED: "accepted", REJECTED: "rejected", INVALID: "invalid", PRECONDITION: "precondition"}


class EvloopError(Exception):
    """可预期的拒绝：携带退出码，由 CLI 统一打印到 stderr。"""

    def __init__(self, message, code=PRECONDITION):
        super().__init__(message)
        self.code = code


def fail(message, code=PRECONDITION):
    raise EvloopError(message, code)


# ---------------------------------------------------------------- 时间

def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def iso(ts):
    return ts.replace(microsecond=0).isoformat()


def parse_iso(text):
    return dt.datetime.fromisoformat(text)


# ---------------------------------------------------------------- 哈希

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def hash_paths(root, rels):
    """把文件或目录展开为 {相对路径: sha256}。路径不存在即拒绝。"""
    out = {}
    for rel in rels:
        full = os.path.join(root, rel)
        if os.path.isdir(full):
            for d, dirs, files in os.walk(full):
                dirs[:] = sorted(x for x in dirs if x != ".git")
                for name in sorted(files):
                    p = os.path.join(d, name)
                    out[norm(os.path.relpath(p, root))] = sha256_file(p)
        elif os.path.isfile(full):
            out[norm(rel)] = sha256_file(full)
        else:
            fail(f"冻结路径不存在：{rel}")
    return out


# ---------------------------------------------------------------- 原子写

def atomic_write_text(path, text):
    """先写同目录临时文件再 os.replace，断电或中断不会留下半截文件。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_write_json(path, obj):
    atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def append_line(path, line):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")
        f.flush()
        os.fsync(f.fileno())


# ---------------------------------------------------------------- 输出摘要

FAILURE_RE = re.compile(r"error|fail|assert|traceback|exception|panic|fatal|错误|失败|异常", re.I)
LINE_CAP = 240


def _clip(line):
    line = line.rstrip()
    return line if len(line) <= LINE_CAP else line[:LINE_CAP - 1] + "…"


def tail_lines(text, k):
    """输出的最后 k 个非空行，每行截断；k<=0 返回空列表。"""
    if k <= 0:
        return []
    return [_clip(ln) for ln in text.splitlines() if ln.strip()][-k:]


def failure_summary(text, k=5):
    """最像失败原因的几行：优先匹配 error / fail / assert 等关键词，否则取末尾。"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    hits = [ln for ln in lines if FAILURE_RE.search(ln)]
    return [_clip(ln) for ln in (hits or lines)[-k:]]


# ---------------------------------------------------------------- 路径规则

def norm(rel):
    rel = str(rel).replace(os.sep, "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.rstrip("/") or "."


def in_scope(rel, scopes):
    """rel 是否落在 scopes 中任一路径（或其子路径）内；"." 表示整个仓库。"""
    rel = norm(rel)
    for s in scopes:
        s = norm(s)
        if s == "." or rel == s or rel.startswith(s + "/"):
            return True
    return False


def overlaps(a, b):
    return in_scope(a, [b]) or in_scope(b, [a])


def inside(child, parent):
    """child 解析后是否等于 parent 或位于其中。"""
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


# ---------------------------------------------------------------- 文件锁

@contextlib.contextmanager
def file_lock(path):
    """契约目录上的排他锁：同一时刻只允许一个会改动状态的命令运行。"""
    try:
        import fcntl
    except ImportError:  # 非 POSIX 平台退化为无锁
        yield
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    handle = open(path, "a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fail("另一个 evloop 命令正在操作这个契约目录；等它结束后再试")
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
