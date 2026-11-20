"""运行约定命令并留存原始输出。

- stdout / stderr 合并为一条流，日志里的先后顺序与真实输出一致；
- POSIX 下命令在独立进程组里运行，超时直接杀掉整个进程组，子进程不会越过预算继续跑；
- 输出按 UTF-8 容错解码，二进制或乱码不会让裁判崩溃。
"""
import os
import signal
import subprocess
import time


class Result:
    __slots__ = ("code", "output", "elapsed", "timed_out")

    def __init__(self, code, output, elapsed, timed_out):
        self.code, self.output, self.elapsed, self.timed_out = code, output, elapsed, timed_out


def _kill_tree(proc):
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        pass


def shell_argv(cmd):
    """约定命令是一行 shell 文本；显式交给系统 shell 解释，Popen 本身不启用 shell 模式。"""
    if os.name == "nt":
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", cmd]
    return ["/bin/sh", "-c", cmd]


def run_command(cmd, cwd, raw_path, timeout=None, env=None, stdin_path=None):
    """timeout 为剩余秒数（None 表示不限）。返回 Result，并把输出写入 raw_path。

    env 为追加到当前环境的变量；stdin_path 给出时把该文件作为标准输入（评审命令读取提示词用）。
    """
    stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
    kwargs = dict(cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=stdin)
    if env:
        kwargs["env"] = dict(os.environ, **{k: str(v) for k, v in env.items()})
    if os.name == "posix":
        kwargs["start_new_session"] = True
    if timeout is not None:
        timeout = max(float(timeout), 0.01)
    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.Popen(shell_argv(cmd), **kwargs)
    finally:
        if stdin_path:
            stdin.close()
    try:
        data, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        try:
            data, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # 有后代脱离进程组仍占着管道
            proc.kill()
            data = b""
    elapsed = time.monotonic() - started
    output = (data or b"").decode("utf-8", errors="replace")
    code = None if timed_out else proc.returncode
    os.makedirs(os.path.dirname(os.path.abspath(raw_path)), exist_ok=True)
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(f"$ {cmd}\n# cwd={cwd} exit={code} elapsed={elapsed:.1f}s timed_out={timed_out}\n")
        f.write(output)
    return Result(code, output, elapsed, timed_out)
