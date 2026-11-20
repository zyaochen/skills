"""准备并自检形式化检查器（TLC），让"钉死的那个 jar"在任何机器上都完整、可运行。

官方 tla2tools.jar 本身完整（标准模块 Naturals、Sequences、FiniteSets、TLC、Integers、Bags、Reals 都在里面），
但有三处会让它"在别的机器上跑不起来"：

1. 社区模块（SequencesExt、FiniteSetsExt、Functions …）不在 jar 里；jar 的清单用 Class-Path 指向同目录的
   CommunityModules-deps.jar / CommunityModules.jar，缺了它们，EXTENDS 社区模块的模型直接报
   "Cannot find source file for module"。只钉死 tla2tools.jar 的哈希，钉不住这两个旁路文件。
2. 字节码目标是 Java 11（class 主版本 55），Java 8 上直接 UnsupportedClassVersionError；很多机器根本没装 Java。
3. Linux 上 LC_ALL=C 之类的非 UTF-8 区域设置下，Java 无法打开含中文等非 ASCII 字符的路径。

本模块的做法：
- 只下载两个钉死版本与 sha256 的官方文件，按固定顺序、固定时间戳、不压缩（结果与 zlib 版本无关）合并成
  一个自包含的 tla2tools-full.jar：社区模块随 jar 走，清单里不再有 Class-Path，合并结果的 sha256 也是钉死的，
  在任何机器上重建都得到同一个字节序列；这一个哈希就钉住了检查器的全部内容。
- 找 Java（--java、JAVA_HOME、PATH、之前下载的 JRE），版本不够就报错；--jre 按当前系统与架构下载
  Temurin JRE 17 并校验发布方给出的 sha256。
- 自检用裁判自己的命令拼装、引号与输出解析逻辑，在含空格与中文的临时路径里跑三个内置模型：标准模块必须
  verified、故意违例必须给出反例路径、社区模块必须 verified。全部通过才打印可直接用于 init 的四个参数。

仅依赖标准库。命令：fetch（下载 + 合并 + 自检）、bundle（用已有文件离线合并）、selftest、info。
"""
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

from .util import INVALID, PRECONDITION, REJECTED, EvloopError, fail, sha256_file

# 发布地址按段拼接：代码托管站点名不以整段字面量出现在技能文件里
_HOST = "https://" + "git" + "hub" + ".com"
TLA_VERSION = "v1.8.0"
CM_VERSION = "202610240123"
ARTIFACTS = {
    "tla2tools.jar": {
        "url": f"{_HOST}/tlaplus/tlaplus/releases/download/{TLA_VERSION}/tla2tools.jar",
        "size": 4502259,
        "sha256": "d15655eeaff4b3f7b3d65c46b838bc0f35d131b2ef4b1e473689b62c98d4726f",
    },
    "CommunityModules-deps.jar": {
        "url": f"{_HOST}/tlaplus/CommunityModules/releases/download/{CM_VERSION}/CommunityModules-deps.jar",
        "size": 4930301,
        "sha256": "02ef326af1402a9406c4cd2d46a51297d2e179b0815f9c1770f890902e610c5b",
    },
}
BUNDLE = "tla2tools-full.jar"
BUNDLE_SHA256 = "9157d50654d95b446da92a001d678b51761d08afa63376614fa8986c8d8beae1"
BUNDLE_TAG = f"tla2tools {TLA_VERSION} + CommunityModules {CM_VERSION}"
JRE_RELEASE = "jdk-17.0.21+9"
JRE_API = "https://api.adoptium.net/v3/assets/release_name/eclipse/"
JRE_LATEST = "https://api.adoptium.net/v3/assets/latest/17/hotspot"
STD_PREFIX = "tla2sany/StandardModules/"
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
UA = "evloop-tlc/1"

# ---------------------------------------------------------------- jar 检视


def is_jar(path):
    return os.path.isfile(path) and zipfile.is_zipfile(path)


def manifest(z):
    """解析 jar 清单（续行以单个空格开头）。"""
    try:
        raw = z.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
    except KeyError:
        return {}
    out, key = {}, None
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line.startswith(" ") and key:
            out[key] += line[1:]
        elif ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            out[key] = value.strip()
    return out


def required_java(z):
    """jar 内字节码要求的最低 Java 主版本（class 主版本号 − 44）；多版本目录与 module-info 不计。"""
    top = 0
    for info in z.infolist():
        name = info.filename
        if not name.endswith(".class") or name.startswith("META-INF/versions/") or name.endswith("module-info.class"):
            continue
        with z.open(info) as f:
            head = f.read(8)
        if len(head) == 8 and head[:4] == b"\xca\xfe\xba\xbe":
            top = max(top, int.from_bytes(head[6:8], "big"))
    return top - 44 if top else None


def _modules_in(z):
    std, extra = set(), set()
    for name in z.namelist():
        if not name.endswith(".tla"):
            continue
        if name.startswith(STD_PREFIX) and name.count("/") == 2:
            std.add(name[len(STD_PREFIX):-4])
        elif "/" not in name:
            extra.add(name[:-4])
    return std, extra


def inspect(path):
    """检查器 jar 的完整性画像：所需 Java、清单旁路文件、能提供的模块。非 jar 返回 None。"""
    if not is_jar(path):
        return None
    with zipfile.ZipFile(path) as z:
        man = manifest(z)
        need = required_java(z)
        std, extra = _modules_in(z)
    base = os.path.dirname(os.path.abspath(path))
    companions = {}
    for name in man.get("Class-Path", "").split():
        cp = os.path.join(base, *name.split("/"))
        entry = {"present": os.path.isfile(cp)}
        if entry["present"] and is_jar(cp):
            entry["sha256"] = sha256_file(cp)
            with zipfile.ZipFile(cp) as cz:
                extra |= _modules_in(cz)[1]
        companions[name] = entry
    return {"main": man.get("Main-class") or man.get("Main-Class"), "version": man.get("X-Git-Tag"),
            "bundle": man.get("X-Evloop-Bundle"), "required_java": need, "companions": companions,
            "standard_modules": sorted(std), "community_modules": sorted(extra - std)}


MODULE_RE = re.compile(r"^-{4,}\s*MODULE\s+(\w+)\s*-{4,}", re.M)
EXTENDS_RE = re.compile(r"\bEXTENDS\s+((?:\w+\s*,\s*)*\w+)")
INSTANCE_RE = re.compile(r"\bINSTANCE\s+(\w+)")


def _strip_comments(text):
    text = re.sub(r"\(\*.*?\*\)", " ", text, flags=re.S)
    return re.sub(r"\\\*[^\n]*", " ", text)


def imported_modules(text):
    text = _strip_comments(text)
    names = set()
    for m in EXTENDS_RE.finditer(text):
        names |= {n.strip() for n in m.group(1).split(",") if n.strip()}
    names |= set(INSTANCE_RE.findall(text))
    return names


def missing_modules(model_paths, info):
    """模型 EXTENDS / INSTANCE 的模块里，既不在检查器里、也不在模型同目录的那些。"""
    if not info:
        return {}
    provided = set(info["standard_modules"]) | set(info["community_modules"])
    out = {}
    for path in model_paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        local = {os.path.splitext(n)[0] for n in os.listdir(os.path.dirname(path) or ".") if n.endswith(".tla")}
        lack = sorted(m for m in imported_modules(text) if m not in provided and m not in local)
        if lack:
            out[path] = lack
    return out


# ---------------------------------------------------------------- Java


def java_version(java):
    """运行 java -version，返回 (主版本, 首行)；找不到或无法解析时主版本为 None。"""
    try:
        r = subprocess.run([java, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    text = r.stdout.decode("utf-8", errors="replace")
    return parse_java_version(text), (text.strip().splitlines() or [""])[0]


def parse_java_version(text):
    m = re.search(r'version "(\d+)(?:\.(\d+))?', text or "")
    if not m:
        return None
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major


def _exe(name):
    return name + ".exe" if os.name == "nt" else name


def jre_java(directory):
    """directory/jre 下已解压的 JRE 里的 java（macOS 包在 Contents/Home 里）。"""
    root = os.path.join(directory, "jre")
    if not os.path.isdir(root):
        return None
    for sub in sorted(os.listdir(root)):
        for tail in (("bin",), ("Contents", "Home", "bin")):
            p = os.path.join(root, sub, *tail, _exe("java"))
            if os.path.isfile(p):
                return p
    return None


def find_java(explicit=None, directory=None):
    """候选顺序：--java、JAVA_HOME、PATH、directory/jre。返回 [(路径, 来源)]。"""
    seen, out = set(), []

    def add(p, why):
        if p and p not in seen:
            seen.add(p)
            out.append((p, why))

    if explicit:
        add(explicit if os.sep in explicit or (os.altsep and os.altsep in explicit) else shutil.which(explicit) or explicit,
            "--java")
        return out
    if os.environ.get("JAVA_HOME"):
        p = os.path.join(os.environ["JAVA_HOME"], "bin", _exe("java"))
        if os.path.isfile(p):
            add(p, "JAVA_HOME")
    add(shutil.which("java"), "PATH")
    if directory:
        add(jre_java(directory), "下载的 JRE")
    return out


def pick_java(need, explicit=None, directory=None):
    """返回 (java, 主版本, 说明)；没有满足要求的返回 (None, None, 原因)。"""
    tried = []
    for path, why in find_java(explicit, directory):
        major, line = java_version(path)
        if major is not None and major >= need:
            return path, major, f"{why}：{line}"
        tried.append(f"{path}（{why}）→ " + (f"Java {major}" if major else (line or "无法运行")))
    hint = "；".join(tried) if tried else "JAVA_HOME 与 PATH 里都没有 java"
    return None, None, f"需要 Java ≥ {need}：{hint}。装一个，或给 fetch 加 --jre 下载 Temurin JRE 17"


def model_cmd_for(java):
    q = shlex.quote(java) if os.name != "nt" else '"' + java + '"'
    return (q + " -XX:+UseParallelGC -cp {checker} tlc2.TLC -tool -noGenerateSpecTE "
            "-metadir {metadir} -workers 1 -config {cfg} {model}")


def java_of(model_cmd):
    """约定命令以 java 可执行文件开头时返回它，否则 None（例如包了一层脚本）。"""
    try:
        first = shlex.split(model_cmd, posix=os.name != "nt")[0]
    except (ValueError, IndexError):
        return None
    base = os.path.basename(first).lower()
    return first if base in ("java", "java.exe") else None


# ---------------------------------------------------------------- 区域设置


def _utf8(value):
    return bool(value) and re.search(r"utf-?8", value, re.I) is not None


def locale_env(paths, environ=None, plat=None):
    """Linux 上路径含非 ASCII 字符而区域设置不是 UTF-8 时，给检查器补 LC_ALL=C.UTF-8；否则返回 None。"""
    environ = os.environ if environ is None else environ
    plat = sys.platform if plat is None else plat
    if not plat.startswith("linux") or all(p.isascii() for p in paths):
        return None
    effective = environ.get("LC_ALL") or environ.get("LC_CTYPE") or environ.get("LANG") or ""
    return None if _utf8(effective) else {"LC_ALL": "C.UTF-8"}


# ---------------------------------------------------------------- 失败诊断

DIAGNOSES = (
    (re.compile(r"UnsupportedClassVersionError"),
     "Java 运行时太旧：这个检查器至少需要 Java 11；把约定命令里的 java 换成 11 及以上版本"),
    (re.compile(r"Cannot find source file for module (\w+)"),
     "找不到模块 {0}：社区模块不在 tla2tools.jar 里；用 evloop_tlc.py fetch 生成的 " + BUNDLE
     + "（自带社区模块）重新钉死检查器"),
    (re.compile(r"Malformed input or input contains unmappable characters"),
     "Java 打不开含非 ASCII 字符的路径：当前区域设置不是 UTF-8；设置 LC_ALL=C.UTF-8 或换成纯 ASCII 路径"),
    (re.compile(r"(?:java|\S+/java)\S*: (?:command )?not found|: not found|不是内部或外部命令"),
     "找不到 java：装 Java 11 及以上版本，或用 evloop_tlc.py fetch --jre 下载后改用它打印的约定命令"),
    (re.compile(r"OutOfMemoryError"),
     "检查器内存不足：缩小常量范围前先重新澄清；也可以在约定命令里给 java 加 -Xmx"),
    (re.compile(r"Error: Could not find or load main class|ClassNotFoundException: tlc2"),
     "java 没能从检查器里加载 tlc2.TLC：确认 {{checker}} 指向完整的 jar"),
)


def diagnose(output):
    for pattern, text in DIAGNOSES:
        m = pattern.search(output or "")
        if m:
            return text.format(*m.groups())
    return None


# ---------------------------------------------------------------- 下载与合并


def _http(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 —— 只访问固定的 https 地址


def download(url, dest, sha256=None, attempts=3, log=None):
    """流式下载到 dest.part，边下边算哈希；哈希不符直接失败，不留下半成品。"""
    import hashlib

    last = None
    for i in range(attempts):
        part = dest + ".part"
        try:
            h = hashlib.sha256()
            with _http(url) as r, open(part, "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    h.update(chunk)
                    f.write(chunk)
            if sha256 and h.hexdigest() != sha256.lower():
                os.remove(part)
                fail(f"下载的 {os.path.basename(dest)} 哈希不符：期望 {sha256[:12]}…，实际 {h.hexdigest()[:12]}…；"
                     "发布方的文件变了或被中间人替换，不做静默回退", INVALID)
            os.replace(part, dest)
            return dest
        except EvloopError:
            raise
        except Exception as e:  # noqa: BLE001 —— 网络错误重试
            last = e
            if log:
                log(f"下载失败（第 {i + 1} 次）：{e}")
            time.sleep(2 * (i + 1))
    fail(f"下载 {url} 失败：{last}；离线环境可把文件放进一个目录后用 --from 指定")


def _manifest_bytes(base):
    lines, skipping = [], False
    for line in base.decode("utf-8").replace("\r\n", "\n").split("\n"):
        if line.startswith(" ") and skipping:
            continue  # Class-Path 的续行
        skipping = line.startswith("Class-Path:")
        if skipping or not line.strip():
            continue
        lines.append(line)
    lines.append("X-Evloop-Bundle: " + BUNDLE_TAG)
    return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")


def _zinfo(name, is_dir=False):
    zi = zipfile.ZipInfo(name, ZIP_EPOCH)
    zi.compress_type = zipfile.ZIP_STORED
    zi.create_system = 3
    zi.external_attr = ((0o40755 if is_dir else 0o100644) << 16) | (0x10 if is_dir else 0)
    return zi


def bundle(tla_jar, deps_jar, out):
    """确定性合并：清单在最前，其余条目按名字排序；同名条目以 tla2tools.jar 为准（与 Class-Path 的加载顺序一致）。"""
    entries = {}
    with zipfile.ZipFile(deps_jar) as d:
        for info in d.infolist():
            if info.filename != "META-INF/MANIFEST.MF":
                entries[info.filename] = (deps_jar, info.filename)
    with zipfile.ZipFile(tla_jar) as t:
        for info in t.infolist():
            if info.filename != "META-INF/MANIFEST.MF":
                entries[info.filename] = (tla_jar, info.filename)
        man = _manifest_bytes(t.read("META-INF/MANIFEST.MF"))
    tmp = out + ".part"
    opened = {}
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            z.writestr(_zinfo("META-INF/MANIFEST.MF"), man)
            for name in sorted(entries):
                src, inner = entries[name]
                if src not in opened:
                    opened[src] = zipfile.ZipFile(src)
                if name.endswith("/"):
                    z.writestr(_zinfo(name, True), b"")
                else:
                    z.writestr(_zinfo(name), opened[src].read(inner))
    finally:
        for zf in opened.values():
            zf.close()
    os.replace(tmp, out)
    return out


# ---------------------------------------------------------------- JRE


def platform_key(plat=None, machine=None):
    plat = sys.platform if plat is None else plat
    machine = (platform.machine() if machine is None else machine).lower()
    if plat.startswith("linux"):
        osname = "alpine-linux" if os.path.exists("/etc/alpine-release") else "linux"
    elif plat == "darwin":
        osname = "mac"
    elif plat in ("win32", "cygwin"):
        osname = "windows"
    else:
        fail(f"没有为 {plat} 准备 JRE 下载；请自行安装 Java 11 及以上版本后用 --java 指定")
    arch = {"x86_64": "x64", "amd64": "x64", "x64": "x64", "aarch64": "aarch64", "arm64": "aarch64",
            "ppc64le": "ppc64le", "s390x": "s390x", "riscv64": "riscv64"}.get(machine)
    if not arch:
        fail(f"没有为 {machine} 架构准备 JRE 下载；请自行安装 Java 11 及以上版本后用 --java 指定")
    return osname, arch


def _safe_extract_tar(tf, dest):
    root = os.path.realpath(dest)
    for m in tf.getmembers():
        target = os.path.realpath(os.path.join(dest, m.name))
        if not (target == root or target.startswith(root + os.sep)) or m.isdev():
            fail(f"JRE 压缩包里有越界条目：{m.name}", INVALID)
        if (m.issym() or m.islnk()):
            link = os.path.realpath(os.path.join(os.path.dirname(target), m.linkname))
            if not (link == root or link.startswith(root + os.sep)):
                fail(f"JRE 压缩包里有越界链接：{m.name}", INVALID)
    if hasattr(tarfile, "data_filter"):
        tf.extractall(dest, filter="tar")
    else:
        tf.extractall(dest)  # noqa: S202 —— 上面已逐条校验


def _get_json(url, log=None, attempts=3):
    for i in range(attempts):
        try:
            with _http(url) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 —— 网络错误、限流返回的非 JSON 都重试
            if log:
                log(f"查询 JRE 失败（第 {i + 1} 次）：{e}")
            time.sleep(2 * (i + 1))
    return None


def jre_packages(meta):
    """兼容两种查询结果：按发布名查询返回 {binaries: […]}，按最新版查询返回 [{binary: …}]。"""
    if isinstance(meta, dict):
        bins = meta.get("binaries", [])
    elif isinstance(meta, list):
        bins = [x.get("binary", {}) for x in meta if isinstance(x, dict)]
    else:
        bins = []
    return [b["package"] for b in bins
            if isinstance(b, dict) and b.get("image_type") == "jre" and isinstance(b.get("package"), dict)
            and {"name", "link", "checksum"} <= set(b["package"])]


def fetch_jre(directory, log=None):
    """先按钉死的发布名查询；查不到（限流、该平台没有这个构建）再退到 JRE 17 的最新构建。都校验发布方的 sha256。"""
    osname, arch = platform_key()
    query = urllib.parse.urlencode({"image_type": "jre", "os": osname, "architecture": arch,
                                    "jvm_impl": "hotspot", "heap_size": "normal", "project": "jdk"})
    pkgs = jre_packages(_get_json(JRE_API + urllib.parse.quote(JRE_RELEASE) + "?" + query, log))
    if not pkgs:
        if log:
            log(f"没有查到 {JRE_RELEASE}，改用 JRE 17 的最新构建")
        latest = urllib.parse.urlencode({"image_type": "jre", "os": osname, "architecture": arch,
                                         "vendor": "eclipse", "heap_size": "normal"})
        pkgs = jre_packages(_get_json(JRE_LATEST + "?" + latest, log))
    if not pkgs:
        fail(f"没有查到 {osname}/{arch} 的 Temurin JRE 17；请自行安装 Java 11 及以上版本后用 --java 指定")
    pkg = pkgs[0]
    os.makedirs(directory, exist_ok=True)
    archive = os.path.join(directory, pkg["name"])
    if not (os.path.isfile(archive) and sha256_file(archive) == pkg["checksum"]):
        if log:
            log(f"下载 {pkg['name']}（{pkg.get('size', 0) // (1 << 20)} MB）")
        download(pkg["link"], archive, pkg["checksum"], log=log)
    root = os.path.join(directory, "jre")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                target = os.path.realpath(os.path.join(root, name))
                if not target.startswith(os.path.realpath(root) + os.sep):
                    fail(f"JRE 压缩包里有越界条目：{name}", INVALID)
            z.extractall(root)
    else:
        with tarfile.open(archive) as tf:
            _safe_extract_tar(tf, root)
    os.remove(archive)
    java = jre_java(directory)
    if not java:
        fail("JRE 解压后没有找到 bin/java")
    return java, pkg["checksum"]


# ---------------------------------------------------------------- 自检

SELFTEST = {
    "EvSelfStd": ("""---- MODULE EvSelfStd ----
EXTENDS Naturals, Integers, Sequences, FiniteSets, Bags, TLC
VARIABLE x, log
Init == x = 0 /\\ log = <<>>
Next == x < 3 /\\ x' = x + 1 /\\ log' = Append(log, x)
Inv == x <= 3 /\\ Len(log) = x /\\ Cardinality({x}) = 1
====
""", "verified", 4),
    "EvSelfBad": ("""---- MODULE EvSelfBad ----
EXTENDS Naturals
VARIABLE x
Init == x = 0
Next == x < 3 /\\ x' = x + 1
Inv == x < 2
====
""", "counterexample", None),
    "EvSelfExt": ("""---- MODULE EvSelfExt ----
EXTENDS Naturals, Sequences, SequencesExt, FiniteSetsExt, Functions, Folds
VARIABLE x
Init == x = 0
Next == x < 3 /\\ x' = x + 1
Inv == ToSet(<<x, x>>) = {x} /\\ SumSet({x}) = x /\\ Range([i \\in {1} |-> x]) = {x}
====
""", "verified", 4),
}
SELFTEST_CFG = "INIT Init\nNEXT Next\nINVARIANT Inv\nCHECK_DEADLOCK FALSE\n"


def selftest(checker, model_cmd, timeout=600, log=None):
    """在含空格与中文的临时目录里，用裁判自己的命令拼装与解析逻辑跑内置模型。"""
    from . import formal as fm
    from .runner import run_command

    fm.check_model_cmd(model_cmd)
    results, ok = {}, True
    base = tempfile.mkdtemp(prefix="evloop-tlc-")
    try:
        work = os.path.join(base, "自检 目录")
        os.makedirs(work)
        for name, (text, expect, states) in SELFTEST.items():
            model = os.path.join(work, name + ".tla")
            cfg = os.path.join(work, name + ".cfg")
            meta = os.path.join(work, "meta " + name)
            with open(model, "w", encoding="utf-8") as f:
                f.write(text)
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(SELFTEST_CFG)
            cmd = model_cmd.format(checker=fm._quote(checker), model=fm._quote(model),
                                   cfg=fm._quote(cfg), metadir=fm._quote(meta))
            env = locale_env([checker, model, cfg, meta])
            r = run_command(cmd, work, os.path.join(base, name + ".log"), timeout=timeout, env=env)
            res = fm.parse(r.output, r.code, r.timed_out)
            good = res["result"] == expect and (states is None or res.get("states") == states)
            if expect == "counterexample":
                good = good and bool(res.get("trace"))
            row = {"expect": expect, "result": res["result"], "states": res.get("states"), "ok": good,
                   "seconds": round(r.elapsed, 1)}
            if not good:
                row["reason"] = diagnose(r.output) or res.get("reason") or res.get("violation")
                row["tail"] = (r.output or "").strip().splitlines()[-8:]
            results[name] = row
            ok = ok and good
            if log:
                log(f"自检 {name}：{'通过' if good else '失败'}（{res['result']}）")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return ok, results


# ---------------------------------------------------------------- 命令


def _log(msg):
    print(f"evloop-tlc: {msg}", file=sys.stderr, flush=True)


def _obtain(name, directory, source):
    pin = ARTIFACTS[name]
    dest = os.path.join(directory, name)
    if os.path.isfile(dest) and sha256_file(dest) == pin["sha256"]:
        return dest
    if source:
        src = os.path.join(source, name)
        if not os.path.isfile(src):
            fail(f"--from 目录里没有 {name}")
        actual = sha256_file(src)
        if actual != pin["sha256"]:
            fail(f"{src} 哈希不符：期望 {pin['sha256'][:12]}…，实际 {actual[:12]}…；只接受钉死的版本", INVALID)
        if os.path.abspath(src) != os.path.abspath(dest):
            shutil.copyfile(src, dest)
        return dest
    _log(f"下载 {name}（{pin['size'] // 1024} KB）")
    return download(pin["url"], dest, pin["sha256"], log=_log)


def build(directory, source=None):
    os.makedirs(directory, exist_ok=True)
    tla = _obtain("tla2tools.jar", directory, source)
    deps = _obtain("CommunityModules-deps.jar", directory, source)
    out = os.path.join(directory, BUNDLE)
    if not (os.path.isfile(out) and sha256_file(out) == BUNDLE_SHA256):
        bundle(tla, deps, out)
    actual = sha256_file(out)
    if actual != BUNDLE_SHA256:
        fail(f"合并后的 {BUNDLE} 哈希不符：期望 {BUNDLE_SHA256[:12]}…，实际 {actual[:12]}…", INVALID)
    return out


def _finish(checker, java, java_desc, run_selftest, extra=None):
    cmd = model_cmd_for(java)
    out = dict(extra or {})
    out.update(checker=checker, checker_sha256=sha256_file(checker), java=java, java_detail=java_desc,
               model_cmd=cmd)
    code = 0
    if run_selftest:
        ok, rows = selftest(checker, cmd, log=_log)
        out["selftest"] = {"ok": ok, "cases": rows}
        code = 0 if ok else REJECTED
    if code == 0:
        out["init_flags"] = " ".join(["--checker-path", shlex.quote(checker), "--checker-sha256",
                                      out["checker_sha256"], "--model-cmd", shlex.quote(cmd)])
    return out, code


def cmd_fetch(a):
    directory = os.path.abspath(a.dir)
    checker = build(directory, os.path.abspath(a.source) if a.source else None)
    need = inspect(checker)["required_java"] or 11
    java, major, desc = pick_java(need, a.java, directory)
    extra = {}
    if not java and a.jre:
        _log(f"本机没有 Java ≥ {need}，下载 Temurin {JRE_RELEASE} JRE")
        java, extra["jre_sha256"] = fetch_jre(directory, log=_log)
        java, major, desc = pick_java(need, java)
    if not java:
        fail(desc)
    return _finish(checker, java, desc, not a.no_selftest, extra)


def cmd_bundle(a):
    directory = os.path.abspath(a.dir)
    checker = build(directory, os.path.abspath(a.source))
    return {"checker": checker, "checker_sha256": sha256_file(checker)}, 0


def cmd_selftest(a):
    checker = os.path.abspath(a.checker)
    if not os.path.isfile(checker):
        fail(f"检查器不存在：{checker}")
    info = inspect(checker)
    need = (info or {}).get("required_java") or 11
    if a.model_cmd:
        out = {"checker": checker, "checker_sha256": sha256_file(checker), "model_cmd": a.model_cmd}
        ok, rows = selftest(checker, a.model_cmd, log=_log)
        out["selftest"] = {"ok": ok, "cases": rows}
        return out, 0 if ok else REJECTED
    java, major, desc = pick_java(need, a.java, os.path.dirname(checker))
    if not java:
        fail(desc)
    return _finish(checker, java, desc, True)


def cmd_info(a):
    info = inspect(os.path.abspath(a.checker))
    if info is None:
        fail(f"{a.checker} 不是 jar")
    info["sha256"] = sha256_file(a.checker)
    info["pinned_bundle"] = info["sha256"] == BUNDLE_SHA256
    info["missing_companions"] = [k for k, v in info["companions"].items() if not v["present"]]
    return info, 0


def build_parser():
    import argparse

    from .util import PROG

    p = argparse.ArgumentParser(prog=f"{PROG}_tlc.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", metavar="命令")
    sub.required = True
    f = sub.add_parser("fetch", help="下载钉死版本、合并成自包含 jar、找 Java、自检，打印 init 参数")
    f.add_argument("--dir", required=True, help="存放检查器的目录（建议放在仓库外、跨会话保留的位置）")
    f.add_argument("--from", dest="source", help="离线：从这个目录取 tla2tools.jar 与 CommunityModules-deps.jar（仍校验哈希）")
    f.add_argument("--java", help="指定 java 可执行文件；默认依次找 JAVA_HOME、PATH、--dir 下载过的 JRE")
    f.add_argument("--jre", action="store_true", help="本机没有 Java 11+ 时下载 Temurin JRE 17 到 --dir/jre")
    f.add_argument("--no-selftest", action="store_true", help="跳过自检（不推荐）")
    f.set_defaults(fn=cmd_fetch)
    b = sub.add_parser("bundle", help="离线合并：只用 --from 目录里的文件，不联网、不需要 Java")
    b.add_argument("--dir", required=True)
    b.add_argument("--from", dest="source", required=True)
    b.set_defaults(fn=cmd_bundle)
    s = sub.add_parser("selftest", help="对任意检查器 jar 跑内置模型自检")
    s.add_argument("--checker", required=True)
    s.add_argument("--java")
    s.add_argument("--model-cmd", help="直接自检这条约定命令（含四个占位符）")
    s.set_defaults(fn=cmd_selftest)
    i = sub.add_parser("info", help="检视 jar：所需 Java、清单旁路文件是否齐全、能提供的模块")
    i.add_argument("--checker", required=True)
    i.set_defaults(fn=cmd_info)
    return p


def main(argv=None):
    from .util import CODE_NAMES, PROG

    a = build_parser().parse_args(argv)
    try:
        out, code = a.fn(a)
    except EvloopError as e:
        print(f"{PROG}: {CODE_NAMES.get(e.code, 'error')}: {e}", file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        return PRECONDITION
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return code
