"""来源快照：把研究用到的网页或文件抓下来，按内容哈希存进运行目录，论断只能引用快照。

每个来源记一条 kind=source 的记录到 attempts.jsonl：
  {"n": 7, "kind": "source", "id": "s1", "url": "https://…", "final_url": "https://…（跟随跳转后）",
   "domain": "example.org", "via": "fetch|file", "sha256": "<文本快照哈希>", "snapshot": "sources/<sha>.txt",
   "bytes": 12345, "content_type": "text/html", "time": "…", "injection": ["…"]（可选）}

裁判读取快照时会重算哈希；快照被改或被删，引用它的论断一律不成立。
域名按跳转后的最终地址计算：短链、跳转页不能把同一个来源算成多个域名。
快照里出现针对评审的注入文本只做标记（injection），提醒引用时别把它当指令。
只用标准库 urllib；不做任何登录、不执行页面脚本。网络抖动（超时、5xx、429）最多重试 2 次。
"""
import html.parser
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .text import injection_hits
from .util import INVALID, atomic_write_text, fail, iso, sha256_file, utc_now

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = 30
USER_AGENT = "evloop-source/1.4 (+snapshot for verifiable citations)"
RETRIES = 2
BINARY_TYPES = ("application/pdf", "application/zip", "application/octet-stream", "image/", "audio/", "video/")
SOURCE_ID_RE = re.compile(r"[A-Za-z0-9_.-]+")


class _TextExtractor(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
             "article", "header", "footer", "blockquote", "pre", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup):
    p = _TextExtractor()
    p.feed(markup)
    p.close()
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(p.parts).splitlines()]
    return "\n".join(ln for ln in lines if ln)


def domain_of(url):
    """来源域名：小写、去掉端口与 www.；本地文件统一记为 local。"""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme in ("", "file"):
        return "local"
    host = (parts.hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _decode(data, charset=None):
    for enc in [charset, "utf-8", "gb18030", "latin-1"]:
        if not enc:
            continue
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _transient(e):
    if isinstance(e, urllib.error.HTTPError):
        return e.code >= 500 or e.code == 429
    return isinstance(e, (urllib.error.URLError, OSError))


def fetch(url, timeout=TIMEOUT, opener=None, sleep=time.sleep):
    """抓取 URL，返回 (文本, content_type, 原始字节数, 跳转后的最终地址)。只接受 http / https / file。

    超时、5xx、429 视为网络抖动，最多重试 RETRIES 次（退避 1s、2s）；其余 4xx 立即失败。
    opener / sleep 可替换，便于离线测试。
    """
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme not in ("http", "https", "file"):
        fail(f"只支持 http、https、file 来源：{url}")
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(RETRIES + 1):
        try:
            with opener(req, timeout=timeout) as resp:  # noqa: S310 —— 用户约定的来源
                data = resp.read(MAX_BYTES + 1)
                headers = getattr(resp, "headers", None)
                ctype = headers.get("Content-Type", "") if headers is not None else ""
                charset = headers.get_content_charset() if headers is not None else None
                final = resp.geturl() if hasattr(resp, "geturl") else url
            break
        except (urllib.error.URLError, OSError, ValueError) as e:
            if attempt < RETRIES and _transient(e):
                sleep(2 ** attempt)
                continue
            fail(f"抓取失败：{url}（{e}）", INVALID)
    if len(data) > MAX_BYTES:
        fail(f"来源超过 {MAX_BYTES // (1024 * 1024)} MB，拒绝快照：{url}")
    if (ctype or "").lower().startswith(BINARY_TYPES):
        fail(f"来源是二进制内容（{ctype.split(';')[0]}）；先转成文本再用 --file 快照：{url}")
    final = final or url
    if urllib.parse.urlsplit(final).scheme not in ("http", "https", "file"):
        fail(f"来源跳转到了不支持的地址：{final}")
    return _to_text(data, ctype, charset, url), ctype or "", len(data), final


def read_file(path):
    with open(path, "rb") as f:
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        fail(f"文件超过 {MAX_BYTES // (1024 * 1024)} MB，拒绝快照：{path}")
    ctype = "text/html" if path.lower().endswith((".html", ".htm")) else "text/plain"
    return _to_text(data, ctype, None, path), ctype, len(data)


def _to_text(data, ctype, charset, name):
    if b"\x00" in data[:4096] and "html" not in (ctype or ""):
        fail(f"来源看起来是二进制内容（例如 PDF）；先转成文本再用 --file 快照：{name}")
    text = _decode(data, charset)
    if "html" in (ctype or "").lower() or re.search(r"(?i)<\s*(html|body|p|div)\b", text[:2048]):
        text = html_to_text(text)
    return text


def snapshot(home, text):
    """把文本快照写进 <home>/sources/<sha>.txt，返回 (sha, 相对路径)。"""
    folder = home.file("sources")
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, ".incoming.txt")
    atomic_write_text(tmp, text)
    sha = sha256_file(tmp)
    rel = f"sources/{sha}.txt"
    os.replace(tmp, home.file(rel))
    return sha, rel


def registered(rows):
    """{来源 id: 记录}；同一 id 只认第一次登记。"""
    out = {}
    for r in rows:
        if r.get("kind") == "source" and r.get("id") not in out:
            out[r["id"]] = r
    return out


def load_sources(home, rows):
    """{来源 id: {"domain", "url", "text"}}；快照缺失或哈希不符时 text 为 None。"""
    out = {}
    for sid, r in registered(rows).items():
        path = home.file(r["snapshot"])
        text = None
        if os.path.isfile(path) and sha256_file(path) == r["sha256"]:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        out[sid] = {"domain": r["domain"], "url": r["url"], "text": text, "via": r.get("via"),
                    "sha256": r["sha256"]}
    return out


def tampered(home, rows):
    return sorted(sid for sid, s in load_sources(home, rows).items() if s["text"] is None)


def add(home, rows, url, sid=None, path=None, note="", opener=None):
    """登记一个来源：抓取（或读本地文件）→ 快照 → 返回待追加的记录。"""
    known = registered(rows)
    if sid is None:
        k = len(known) + 1
        while f"s{k}" in known:
            k += 1
        sid = f"s{k}"
    if not SOURCE_ID_RE.fullmatch(sid):
        fail("--id 必须由字母、数字、'.'、'_'、'-' 组成")
    if sid in known:
        fail(f"来源 {sid} 已登记（{known[sid]['url']}）；换一个 --id")
    if path:
        if not os.path.isfile(path):
            fail(f"--file 不存在：{path}")
        text, ctype, size = read_file(path)
        via, final = "file", url
    else:
        text, ctype, size, final = fetch(url, opener=opener)
        via = "fetch"
    if not text.strip():
        fail(f"来源没有可读的文本：{url}")
    sha, rel = snapshot(home, text)
    rec = {"kind": "source", "id": sid, "url": url, "domain": domain_of(final), "via": via,
           "sha256": sha, "snapshot": rel, "bytes": size, "content_type": ctype,
           "time": iso(utc_now())}
    if final != url:
        rec["final_url"] = final
    hits = injection_hits(text)
    if hits:
        rec["injection"] = hits[:5]
    dup = next((r["id"] for r in known.values() if r.get("sha256") == sha), None)
    if dup:
        rec["duplicate_of"] = dup
    if note:
        rec["note"] = note
    return rec
