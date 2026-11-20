"""External tools: whiteboard-cli (local render + geometric check) and lark-cli (write / export a Lark whiteboard).

lark-cli only reads and writes files under cwd or /tmp, so every call runs with cwd=/tmp and stages files there.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import time

WBCLI = shlex.split(os.environ.get('LFIG_WBCLI', 'npx -y @larksuite/whiteboard-cli@^0.2.12'))
LARK = shlex.split(os.environ.get('LFIG_LARK_CLI', 'lark-cli'))
STATE = os.path.expanduser(os.environ.get('LFIG_STATE', '~/.cache/lark-figure'))
TRIES = 3
TOKEN = re.compile(r'[A-Za-z0-9_-]+')


class ToolError(RuntimeError):
    pass


def check_token(token):
    """Tokens end up in file names under /tmp and the backup dir, so anything but [A-Za-z0-9_-] is refused."""
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ToolError(f'whiteboard token {token!r} is not valid; expected letters, digits, "_" or "-" only '
                        '(copy it from <whiteboard token="…"> in `lark-cli docs +fetch` output)')
    return token


def _run(cmd, timeout=180):
    try:
        return subprocess.run(cmd, cwd='/tmp', capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as e:
        raise ToolError(f'{cmd[0]} not found; install it (see references/publish.md)') from e
    except subprocess.TimeoutExpired as e:
        raise ToolError(f'{" ".join(cmd[:4])} timed out after {timeout}s') from e


def render_png(svg_path, png_path):
    r = _run(WBCLI + ['-i', os.path.abspath(svg_path), '-f', 'svg', '-o', os.path.abspath(png_path)])
    if r.returncode or not os.path.exists(png_path):
        raise ToolError(f'whiteboard-cli render failed: {(r.stderr or r.stdout)[-400:]}')
    return png_path


def wb_check(svg_path):
    """whiteboard-cli --check: the board's own text-overflow / node-overlap detector. Returns list of issues."""
    r = _run(WBCLI + ['-i', os.path.abspath(svg_path), '-f', 'svg', '--check'])
    out = (r.stdout or '').strip()
    try:
        data = json.loads(out[out.index('{'):]) if '{' in out else {}
    except ValueError:
        data = {}
    if r.returncode and not data:
        raise ToolError(f'whiteboard-cli --check failed: {(r.stderr or r.stdout)[-400:]}')
    check = (data.get('data') or {}).get('check') or {}
    return check.get('issues') or []


def _lark(*args):
    return _run(LARK + list(args))


def _ok(r):
    try:
        return json.loads(r.stdout).get('ok') is True
    except ValueError:
        return '"ok": true' in (r.stdout or '')


def backup(token):
    """Save the board's current raw nodes so a bad put can be rolled back with `figure.py restore`."""
    check_token(token)
    os.makedirs(os.path.join(STATE, 'bak'), exist_ok=True)
    dst = os.path.join(STATE, 'bak', f'{token}-{int(time.time())}.json')
    tmp = f'/tmp/lfig_bak_{token}.json'
    r = _lark('whiteboard', '+query', '--whiteboard-token', token, '--output_as', 'raw', '--output', tmp,
              '--overwrite', '--as', 'user')
    if r.returncode or not os.path.exists(tmp):
        raise ToolError(f'backup of {token} failed (need read permission?): {(r.stderr or r.stdout)[-300:]}')
    shutil.move(tmp, dst)
    return dst


def put(token, svg_path, dry=False):
    """Overwrite a whiteboard with an SVG. Always dry-runs first; real write only when dry=False."""
    check_token(token)
    staged = f'/tmp/lfig_put_{token}.svg'
    shutil.copy(os.path.abspath(svg_path), staged)
    base = ['whiteboard', '+update', '--whiteboard-token', token, '--source', '@' + staged,
            '--input_format', 'svg', '--overwrite', '--as', 'user']
    r = _lark(*base, '--dry-run')
    if r.returncode:
        raise ToolError(f'dry-run rejected: {(r.stderr or r.stdout)[-400:]}')
    if dry:
        return {'dry_run': True, 'request': r.stdout[-600:]}
    bak = backup(token)
    err = ''
    for i in range(TRIES):
        r = _lark(*base)
        if _ok(r):
            return {'ok': True, 'token': token, 'backup': bak}
        err = (r.stderr or r.stdout)[-400:]
        time.sleep(4 * (i + 1))
    raise ToolError(f'put failed after {TRIES} tries (backup at {bak}): {err}')


def restore(token, raw_path):
    check_token(token)
    staged = f'/tmp/lfig_restore_{token}.json'
    with open(raw_path, encoding='utf-8') as f:
        data = json.load(f)
    with open(staged, 'w', encoding='utf-8') as f:
        json.dump(data if 'nodes' in data else {'nodes': data}, f, ensure_ascii=False)
    r = _lark('whiteboard', '+update', '--whiteboard-token', token, '--source', '@' + staged,
              '--input_format', 'raw', '--overwrite', '--as', 'user')
    if not _ok(r):
        raise ToolError(f'restore failed: {(r.stderr or r.stdout)[-400:]}')
    return {'ok': True}


def preview(token, out_path):
    """Export what Lark actually renders. Retries once after 2 s: a fresh write is not always readable at once."""
    check_token(token)
    stem = f'/tmp/lfig_prev_{token}_{int(time.time())}'
    for i in range(TRIES):
        _lark('whiteboard', '+query', '--whiteboard-token', token, '--output_as', 'image', '--output', stem,
              '--overwrite', '--as', 'user')
        for ext in ('.jpg', '.png', ''):
            if os.path.exists(stem + ext) and os.path.getsize(stem + ext) > 0:
                shutil.move(stem + ext, out_path)
                return out_path
        time.sleep(2 * (i + 1))
    raise ToolError(f'preview export of {token} failed; check read permission and token')
