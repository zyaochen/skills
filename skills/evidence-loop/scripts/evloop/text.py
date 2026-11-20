"""研究 / 文档场景的硬检查：纯函数，不碰 git、不跑命令，便于单测。

文档规格（--doc-spec，init 时冻结并复制到运行目录）：
  {"headings":   ["背景", "结论"],                 # 必须以 Markdown 标题出现
   "min_chars":  800,                              # 正文最少字符数（去掉空白后）
   "forbidden":  ["\\\\bTODO\\\\b", "待补充"],         # 不得出现的正则；不给时用 DEFAULT_FORBIDDEN
   "claims":     "docs/claims.jsonl",              # 论断文件（研究场景必填，须在可编辑范围内）
   "doctest":    false,                            # 为 true 时对草稿跑 python -m doctest
   "cite_numbers": true,                           # 含数字的句子必须引用论断，且数字要出现在所引摘录里
   "questions":  [{"id": "q1", "text": "…", "min_sources": 2,
                   "heading": "市场规模", "accept": "python3 checks/q1.py"}]}

论断文件每行一个 JSON：{"id": "c1", "question": "q1", "source": "s1", "quote": "原文摘录"}。
草稿用 Markdown 脚注 [^c1] 引用论断。规则：
  - 草稿引用了论断文件里没有的 ID → 编造引用；
  - 论断的 quote 必须逐字（空白与全半角规范化后）出现在来源快照里；
  - 只有被草稿引用、且摘录核对通过的论断才计入问题覆盖；
  - 每个问题被覆盖的不同来源域名数不少于 min_sources；内容完全相同的快照（镜像、转载）只算一个来源；
  - cite_numbers 为 true 时，正文里每个含数字的句子都要带脚注，句中的数字要出现在所引论断的摘录里。
"""
import json
import re
import unicodedata

DEFAULT_FORBIDDEN = [r"\bTODO\b", r"\bTBD\b", r"\bFIXME\b", "待补充", "待完善", r"(?i)lorem ipsum"]
SPEC_KEYS = {"headings", "min_chars", "forbidden", "claims", "doctest", "questions", "cite_numbers"}
QUESTION_KEYS = {"id", "text", "min_sources", "heading", "accept"}
ID_RE = re.compile(r"[A-Za-z0-9_.-]+")
CITE_RE = re.compile(r"\[\^([A-Za-z0-9_.-]+)\]")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.M)
# 数字：前面不能紧贴字母 / 数字 / 下划线 / 小数点（排除 p99、c1、v1.3 这类标识符），千分位逗号与百分号一并取下
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.^])\d+(?:[.,]\d+)*")
# 句子切分：中文句末标点、换行、英文句点后的空白；紧跟在句末标点后的脚注归前一句
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])(?!\s*\[\^)|\n+|(?<=\.)\s+(?!\[\^)")
FENCE_RE = re.compile(r"^\s{0,3}(```|~~~).*?^\s{0,3}\1[^\n]*$", re.M | re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
FOOTNOTE_DEF_RE = re.compile(r"^\s{0,3}\[\^[^\]]+\]:.*$", re.M)
LIST_MARK_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)

# 针对评审模型的注入：草稿里出现即判无效；来源快照里出现只做标记
INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)",
    r"(?i)disregard\s+(all\s+|the\s+)?(previous|prior|above|system)",
    r"(?i)system\s+prompt",
    r"(?i)(give|assign|rate|score)\s+(this|it|the\s+(document|report|draft))\s+(a\s+|an\s+)?"
    r"(10|ten|full|perfect|maximum|max)",
    r"(?im)^\s*SCORE\s*[:：]\s*-?\d",
    r"忽略(之前|以上|前面|上面|先前)的?(所有|全部)?(指令|提示|规则|要求)",
    r"(给|打)(这篇|本文|它|该文档|这份)?(文档|报告)?(满分|10\s*分|十分)",
    r"系统提示词",
]
_INJECTION = [re.compile(p) for p in INJECTION_PATTERNS]


class SpecError(ValueError):
    pass


# ---------------------------------------------------------------- 规格

def check_spec(spec):
    """校验文档规格；返回规范化后的副本，不合法抛 SpecError。"""
    if not isinstance(spec, dict):
        raise SpecError("文档规格必须是 JSON 对象")
    unknown = set(spec) - SPEC_KEYS
    if unknown:
        raise SpecError(f"文档规格里有未知字段：{sorted(unknown)}")
    out = dict(spec)
    headings = spec.get("headings", [])
    if not isinstance(headings, list) or not all(isinstance(h, str) and h.strip() for h in headings):
        raise SpecError("headings 必须是非空字符串列表")
    out["headings"] = headings
    min_chars = spec.get("min_chars", 0)
    if not isinstance(min_chars, int) or isinstance(min_chars, bool) or min_chars < 0:
        raise SpecError("min_chars 必须是非负整数")
    out["min_chars"] = min_chars
    forbidden = spec.get("forbidden", DEFAULT_FORBIDDEN)
    if not isinstance(forbidden, list) or not all(isinstance(p, str) for p in forbidden):
        raise SpecError("forbidden 必须是正则字符串列表")
    for p in forbidden:
        try:
            re.compile(p)
        except re.error as e:
            raise SpecError(f"forbidden 里的正则不合法：{p}（{e}）") from None
    out["forbidden"] = forbidden
    if spec.get("claims") is not None and not (isinstance(spec["claims"], str) and spec["claims"].strip()):
        raise SpecError("claims 必须是论断文件的相对路径")
    if not isinstance(spec.get("doctest", False), bool):
        raise SpecError("doctest 必须是布尔值")
    out["doctest"] = bool(spec.get("doctest", False))
    if not isinstance(spec.get("cite_numbers", False), bool):
        raise SpecError("cite_numbers 必须是布尔值")
    out["cite_numbers"] = bool(spec.get("cite_numbers", False))
    if out["cite_numbers"] and not spec.get("claims"):
        raise SpecError("cite_numbers 需要 claims：数字要能追溯到论断摘录")
    questions = spec.get("questions", [])
    if not isinstance(questions, list):
        raise SpecError("questions 必须是列表")
    seen = set()
    normalized = []
    for q in questions:
        if not isinstance(q, dict) or not isinstance(q.get("id"), str) or not ID_RE.fullmatch(q["id"]):
            raise SpecError("每个问题都需要由字母、数字、'.'、'_'、'-' 组成的 id")
        extra = set(q) - QUESTION_KEYS
        if extra:
            raise SpecError(f"问题 {q['id']} 有未知字段：{sorted(extra)}")
        if q["id"] in seen:
            raise SpecError(f"问题 id 重复：{q['id']}")
        seen.add(q["id"])
        ms = q.get("min_sources", 1)
        if not isinstance(ms, int) or isinstance(ms, bool) or ms < 0:
            raise SpecError(f"问题 {q['id']} 的 min_sources 必须是非负整数")
        normalized.append(dict(q, min_sources=ms))
    out["questions"] = normalized
    return out


# ---------------------------------------------------------------- 文本工具

def normalize(text):
    """逐字比对用的规范化：NFKC（全半角统一）、弯引号转直引号、空白折叠。大小写保留。"""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x00A0: " "})
    return re.sub(r"\s+", " ", text).strip()


def headings(text):
    return [normalize(h) for h in HEADING_RE.findall(text or "")]


def citations(text):
    return list(dict.fromkeys(CITE_RE.findall(text or "")))


def injection_hits(text):
    hits = []
    for rx in _INJECTION:
        m = rx.search(text or "")
        if m:
            hits.append(m.group(0).strip()[:80])
    return hits


def numbers(text):
    """文本里的数字，去掉千分位逗号后返回集合（"12,000" 与 "12000" 视为同一个数）。"""
    return {m.group(0).replace(",", "") for m in NUMBER_RE.finditer(text or "")}


def prose_sentences(text):
    """正文句子：去掉代码块、行内代码、标题行、脚注定义与列表序号后切句。"""
    text = FENCE_RE.sub("\n", text or "")
    text = FOOTNOTE_DEF_RE.sub("", text)
    text = HEADING_RE.sub("", text)
    text = INLINE_CODE_RE.sub(" ", text)
    text = LIST_MARK_RE.sub("", text)
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s and s.strip()]


def number_citations(text, quotes):
    """含数字的句子必须带脚注，且句中每个数字都要出现在所引论断的摘录里。

    quotes: {论断 id: 摘录}。返回 {"uncited": [句子…], "unsupported": [(数字, 句子)…]}。
    """
    uncited, unsupported = [], []
    for sentence in prose_sentences(text):
        cites = CITE_RE.findall(sentence)
        bare = CITE_RE.sub(" ", sentence)
        found = numbers(bare)
        if not found:
            continue
        if not cites:
            uncited.append(sentence[:60])
            continue
        allowed = set()
        for cid in cites:
            allowed |= numbers(normalize(quotes.get(cid, "")))
        for n in sorted(found - allowed):
            unsupported.append((n, sentence[:60]))
    return {"uncited": uncited, "unsupported": unsupported}


def body_chars(text):
    return len(re.sub(r"\s+", "", text or ""))


def parse_claims(text):
    """解析论断文件：返回 (论断列表, 问题列表)。问题是可读的字符串，用于失败原因。"""
    claims, problems = [], []
    seen = set()
    for i, line in enumerate((text or "").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            problems.append(f"论断文件第 {i} 行不是 JSON：{e}")
            continue
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not ID_RE.fullmatch(row["id"]):
            problems.append(f"论断文件第 {i} 行缺少合法的 id")
            continue
        if row["id"] in seen:
            problems.append(f"论断 id 重复：{row['id']}")
            continue
        seen.add(row["id"])
        for key in ("source", "quote"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                problems.append(f"论断 {row['id']} 缺少 {key}")
                break
        else:
            claims.append(row)
    return claims, problems


def skeleton(spec):
    """只有标题、没有内容的骨架草稿，用来证明检查能区分"有内容"与"只有架子"。"""
    lines = ["# 草稿", ""]
    for h in spec.get("headings", []) + [q["heading"] for q in spec.get("questions", []) if q.get("heading")]:
        lines += [f"## {h}", "", "…", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- 检查

def check_document(spec, text, claims_text=None, sources=None, require_claims=False):
    """对草稿做全部硬检查。

    sources: {来源 id: {"domain": str, "text": str 或 None, "url": str, "reject": 可选原因}}；
    text 为 None 表示快照缺失或被改动，reject 表示契约不接受这类来源。

    返回 {"ok", "failures", "integrity", "questions", "claims", "cited", "chars", "injection"}。
    integrity 是 failures 的子集：编造引用、摘录对不上快照、注入文本、论断文件损坏——
    这些是诚信问题，裁判判为无效并回滚；其余（缺标题、覆盖不足、占位符）只是未完成。
    """
    sources = sources or {}
    failures, integrity = [], []
    if text is None:
        return {"ok": False, "failures": ["草稿文件不存在"], "integrity": [], "questions": {},
                "claims": {}, "cited": [], "chars": 0, "injection": []}
    chars = body_chars(text)
    if chars < spec.get("min_chars", 0):
        failures.append(f"正文只有 {chars} 个字符，少于约定的 {spec['min_chars']}")
    present = set(headings(text))
    wanted = list(spec.get("headings", [])) + [q["heading"] for q in spec.get("questions", []) if q.get("heading")]
    missing = [h for h in dict.fromkeys(wanted) if normalize(h) not in present]
    if missing:
        failures.append(f"缺少约定的标题：{missing}")
    for pattern in spec.get("forbidden", DEFAULT_FORBIDDEN):
        m = re.search(pattern, text)
        if m:
            failures.append(f"出现了禁用内容 /{pattern}/：{m.group(0)[:40]}")
    injection = injection_hits(text)
    if injection:
        integrity.append(f"草稿里有针对评审的注入文本：{injection}")

    cited = citations(text)
    claim_rows, claim_status = [], {}
    if spec.get("claims"):
        if claims_text is None:
            if require_claims or cited:
                failures.append(f"论断文件不存在：{spec['claims']}")
        else:
            claim_rows, problems = parse_claims(claims_text)
            integrity += problems
    known = {c["id"]: c for c in claim_rows}
    fabricated = [cid for cid in cited if cid not in known]
    if fabricated:
        integrity.append(f"草稿引用了论断文件里不存在的论断（编造引用）：{fabricated}")
    question_ids = {q["id"] for q in spec.get("questions", [])}
    for c in claim_rows:
        src = sources.get(c["source"])
        status = {"question": c.get("question"), "source": c["source"], "cited": c["id"] in cited,
                  "domain": src.get("domain") if src else None,
                  "sha256": (src.get("sha256") or c["source"]) if src else None, "ok": False}
        if c.get("question") and c["question"] not in question_ids:
            status["reason"] = f"问题 {c['question']} 不在规格里"
        elif src is None:
            status["reason"] = f"来源 {c['source']} 没有登记快照（先运行 source add）"
        elif src.get("reject"):
            status["reason"] = src["reject"]
        elif src.get("text") is None:
            status["reason"] = f"来源 {c['source']} 的快照缺失或已被改动"
        elif normalize(c["quote"]) not in normalize(src["text"]):
            status["reason"] = "摘录没有逐字出现在来源快照里"
        else:
            status["ok"] = True
        claim_status[c["id"]] = status
        if status["cited"] and not status["ok"]:
            integrity.append(f"论断 {c['id']}：{status['reason']}")

    coverage = {}
    for q in spec.get("questions", []):
        good = [cid for cid, s in claim_status.items() if s["question"] == q["id"] and s["cited"] and s["ok"]]
        domains = sorted({claim_status[cid]["domain"] for cid in good})
        # 镜像 / 转载：不同域名、内容完全相同的快照只算一个来源
        distinct = min(len(domains), len({claim_status[cid]["sha256"] for cid in good}))
        ok = distinct >= q["min_sources"]
        coverage[q["id"]] = {"text": q.get("text", ""), "claims": good, "domains": domains,
                             "distinct": distinct, "min_sources": q["min_sources"], "ok": ok}
        if not ok:
            mirror = "（内容相同的快照只算一个）" if distinct < len(domains) else ""
            failures.append(f"问题 {q['id']} 只有 {distinct} 个不同来源域名的有效引用{mirror}，"
                            f"少于约定的 {q['min_sources']}")
    nums = None
    if spec.get("cite_numbers"):
        nums = number_citations(text, {cid: c["quote"] for cid, c in known.items()})
        if nums["uncited"]:
            failures.append(f"{len(nums['uncited'])} 处含数字的句子没有引用论断：" +
                            "；".join(nums["uncited"][:3]))
        if nums["unsupported"]:
            failures.append(f"{len(nums['unsupported'])} 个数字不在所引论断的摘录里：" +
                            "；".join(f"{n}（{s}）" for n, s in nums["unsupported"][:3]))
    failures = integrity + failures
    out = {"ok": not failures, "failures": failures, "integrity": integrity, "questions": coverage,
           "claims": claim_status, "cited": cited, "chars": chars, "injection": injection}
    if nums is not None:
        out["numbers"] = {"uncited": len(nums["uncited"]), "unsupported": len(nums["unsupported"])}
    return out


def discriminates(spec, require_claims=False):
    """空草稿必须不通过；只有骨架的草稿也必须不通过。返回 (是否具区分度, 说明)。"""
    if check_document(spec, "", "", {}, require_claims)["ok"]:
        return False, "空草稿也能通过全部硬检查"
    if check_document(spec, skeleton(spec), "", {}, require_claims)["ok"]:
        return False, "只有标题骨架的草稿也能通过全部硬检查"
    return True, ""
