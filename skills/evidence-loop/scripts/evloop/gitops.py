"""git 调用封装。

相比直接拼 porcelain 文本，这里统一做了三件事：
- 用 -z 输出解析路径，带空格、引号、非 ASCII 的文件名不会被误判；
- diff 一律 --no-renames，把"移动越界文件进可编辑目录"拆成删除 + 新增，越界删除也能被抓到；
- git-dir / common-dir 自行解析为绝对路径，不依赖 git 2.31 才有的 --path-format。
"""
import contextlib
import os
import shutil
import subprocess
import tempfile

from .util import STATE_DIR, fail, in_scope


def _run(cwd, args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def git(cwd, *args, check=True, strip=True):
    r = _run(cwd, args)
    if check and r.returncode != 0:
        fail(f"git {' '.join(args)} 失败：{r.stderr.strip()}")
    return r.stdout.strip() if strip else r.stdout


def git_ok(cwd, *args):
    return _run(cwd, args).returncode == 0


def is_work_tree(path):
    return os.path.isdir(path) and git_ok(path, "rev-parse", "--is-inside-work-tree")


def require_work_tree(path, what="路径"):
    if not is_work_tree(path):
        fail(f"{what} 不是 git 工作区：{path}")


def head(cwd):
    return git(cwd, "rev-parse", "HEAD")


def toplevel(cwd):
    return os.path.realpath(git(cwd, "rev-parse", "--show-toplevel"))


def _abs_dir(cwd, rel):
    return os.path.realpath(rel if os.path.isabs(rel) else os.path.join(cwd, rel))


def git_dir(cwd):
    return _abs_dir(cwd, git(cwd, "rev-parse", "--git-dir"))


def common_dir(cwd):
    return _abs_dir(cwd, git(cwd, "rev-parse", "--git-common-dir"))


def is_linked_worktree(cwd):
    return git_dir(cwd) != common_dir(cwd)


def has_commit(cwd, sha):
    return git_ok(cwd, "cat-file", "-e", f"{sha}^{{commit}}")


def is_ancestor(cwd, older, newer="HEAD"):
    return git_ok(cwd, "merge-base", "--is-ancestor", older, newer)


def current_branch(cwd):
    return git(cwd, "rev-parse", "--abbrev-ref", "HEAD")


def branch_exists(cwd, name):
    return git_ok(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")


def _split_z(out):
    return [p for p in out.split("\0") if p]


def status_entries(cwd, *pathspec, ignored=False):
    """[(XY, path)]，未跟踪目录展开为逐个文件。"""
    args = ["status", "--porcelain", "-z", "--untracked-files=all"]
    if ignored:
        args.append("--ignored")
    if pathspec:
        args += ["--", *pathspec]
    parts = git(cwd, *args, strip=False).split("\0")
    entries, i = [], 0
    while i < len(parts):
        item = parts[i]
        i += 1
        if len(item) < 4:
            continue
        code, path = item[:2], item[3:]
        if code[0] in "RC":  # 重命名 / 复制后紧跟原路径
            i += 1
        entries.append((code, path))
    return entries


def stray_files(cwd, generated=()):
    """工作区里未提交的改动，声明为生成路径的除外。"""
    return [p for code, p in status_entries(cwd) if not in_scope(p, generated)]


def hidden_state_files(cwd):
    """工作区里被忽略、git status 看不到、git clean -fd 也删不掉的状态目录文件。"""
    return [p for code, p in status_entries(cwd, STATE_DIR, ignored=True) if code == "!!"]


def changed_between(cwd, base, tip="HEAD"):
    return _split_z(git(cwd, "diff", "--name-only", "--no-renames", "-z", base, tip, strip=False))


def diff_size(cwd, base, tip="HEAD"):
    """base..tip 的增删行数（二进制文件不计）。"""
    added = deleted = 0
    for line in git(cwd, "diff", "--numstat", "--no-renames", base, tip).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            added += int(parts[0]) if parts[0].isdigit() else 0
            deleted += int(parts[1]) if parts[1].isdigit() else 0
    return {"added": added, "deleted": deleted}


def resolve_commit(cwd, rev):
    r = _run(cwd, ["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"])
    return r.stdout.strip() if r.returncode == 0 else None


@contextlib.contextmanager
def temp_worktree(cwd, commit):
    """在系统临时目录检出一个分离 HEAD 的临时 worktree，用完即删，不影响循环工作区。"""
    base = tempfile.mkdtemp(prefix="evloop-")
    path = os.path.join(base, "wt")
    try:
        git(cwd, "worktree", "add", "--detach", "-q", path, commit)
        yield path
    finally:
        git(cwd, "worktree", "remove", "--force", path, check=False)
        shutil.rmtree(base, ignore_errors=True)
        git(cwd, "worktree", "prune", check=False)


def porcelain_lines(cwd):
    return sorted(f"{code} {p}" for code, p in status_entries(cwd))


def reset_to(cwd, commit):
    git(cwd, "reset", "--hard", "-q", commit)


def rollback(cwd, best):
    git(cwd, "reset", "--hard", "-q", best)
    git(cwd, "clean", "-fdq")


def add_exclude(repo, line="/" + STATE_DIR + "/"):
    """把状态目录写入 .git/info/exclude：只在本克隆生效，不进入共享历史。"""
    path = os.path.join(git_dir(repo), "info", "exclude")
    content = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    covered = {raw.strip().lstrip("/").rstrip("/") for raw in content.splitlines()}
    if STATE_DIR in covered:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        if content and not content.endswith("\n"):
            f.write("\n")
        f.write(line + "\n")
    return True


def version():
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, text=True)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    digits = []
    for tok in r.stdout.split():
        if tok[:1].isdigit():
            for piece in tok.split(".")[:3]:
                num = "".join(ch for ch in piece if ch.isdigit())
                digits.append(int(num or 0))
            break
    return tuple(digits) if digits else None
