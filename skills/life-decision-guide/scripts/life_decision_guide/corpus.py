"""读取并校验内置快照，把章节切成带出处的完整条目。"""
import hashlib
import json
from urllib.parse import quote

from . import config


class GuideError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def load_json(name):
    return json.loads((config.REFERENCES / name).read_text(encoding="utf-8"))


def evidence_state(raw):
    """仅检测原文提醒；没有命中不表示证据可靠或完成独立核验。"""
    excerpts = [line for line in raw.splitlines() if config.SOURCE_WARNING.search(line)]
    return {
        "source_warning": {
            "status": "detected" if excerpts else "not_detected",
            "excerpts": excerpts,
            "method": "lexical",
        },
        "independent_source_check": {
            "status": "not_checked", "checked_at": None, "sources": [],
        },
        "current_applicability_check": {
            "status": "not_checked", "checked_at": None, "sources": [],
            "region": None, "population": None,
        },
    }


def ratio_for(tags, spec):
    weights = spec["weights"]
    try:
        score = sum(weights[key][tags[key]] for key in config.COST_KEYS)
        level = tags["收益"]
    except KeyError:
        return None, None
    if level not in config.BENEFIT_LEVELS:
        return score, None
    if level == "大":
        ratio = "极高" if score == 0 else "高" if score <= 2 else "一般"
    elif level == "中":
        ratio = "高" if score == 0 else "一般"
    else:
        ratio = "一般"
    return score, ratio


def _verified_chapter_paths(meta):
    paths = sorted(config.BOOK.glob("*.md"))
    if not paths:
        raise GuideError("SNAPSHOT_MISSING", "未找到内置章节，不能用记忆替代正文。")
    expected = {
        rel for rel in meta["source_files_sha256"]
        if rel.startswith("book/") and rel.endswith(".md")
    }
    missing = sorted(expected - {"book/" + path.name for path in paths})
    if missing:
        raise GuideError("SNAPSHOT_MISSING", "内置章节不完整，缺失：" + "、".join(missing))
    if len(expected) != meta["chapter_count"]:
        raise GuideError("SNAPSHOT_INTEGRITY", "章节清单与版本记录不一致；请恢复同版本快照。")
    for path in paths:
        _verify(meta, "book/" + path.name, path)
    return paths


def _verify(meta, rel, path):
    digest = meta["source_files_sha256"].get(rel)
    if not path.is_file():
        raise GuideError("SNAPSHOT_MISSING", f"内置资料缺失：{rel}")
    if not digest or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise GuideError("SNAPSHOT_INTEGRITY", f"源文件校验失败：{rel}；请恢复同版本快照。")


def verified_text(rel):
    """读取 references/source 下任一受哈希保护的文件。"""
    meta = load_json("provenance.json")
    path = config.SOURCE_ROOT / rel
    _verify(meta, rel, path)
    return path.read_text(encoding="utf-8")


def _doc_in_scope(rel, scope):
    if rel in config.DOC_TOOLING:
        return False
    is_record = rel.startswith(config.DOC_RECORDS_PREFIX)
    return scope == "all" or (scope == "records") == is_record


def doc_files(scope="articles"):
    meta = load_json("provenance.json")
    rels = sorted(
        r for r in meta["source_files_sha256"]
        if r.startswith("docs/") and r.endswith(".md") and _doc_in_scope(r, scope)
    )
    for rel in rels:
        _verify(meta, rel, config.SOURCE_ROOT / rel)
    return meta, rels


def author_flags(fields):
    todo_text = "\n".join(fields.get(name, "") for name in config.AUTHOR_TODO_FIELDS)
    return {
        "dispute": bool(config.AUTHOR_DISPUTE.search(fields.get("备注", ""))),
        "todo": bool(config.AUTHOR_TODO.search(todo_text)),
    }


def _chapter_entries(path, meta, ranking_spec):
    rel = "book/" + path.name
    text = path.read_text(encoding="utf-8")
    section_match = config.SECTION_HEADING.search(text)
    if not section_match:
        raise GuideError("SNAPSHOT_INTEGRITY", f"缺少章节标题：{rel}")
    section = int(section_match.group(1))
    headers = list(config.ITEM_HEADING.finditer(text))
    for idx, match in enumerate(headers):
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
        raw = text[match.start():end].rstrip()
        start_line = text.count("\n", 0, match.start()) + 1
        end_line = start_line + len(raw.splitlines()) - 1
        tags_match = config.TAGS.search(raw)
        tags = dict(config.TAG_PAIRS.findall(tags_match.group(1))) if tags_match else {}
        fields = dict(config.FIELDS.findall(raw))
        score, ratio = ratio_for(tags, ranking_spec)
        flags = author_flags(fields)
        grade = config.AUTHOR_GRADE.match(fields.get("证据等级", ""))
        yield {
            "id": f"{section}:{int(match.group(1))}", "section": section,
            "section_title": section_match.group(2), "item": int(match.group(1)),
            "title": match.group(2), "file": rel,
            "line_start": start_line, "line_end": end_line,
            "url": f'{meta["repository"]}/blob/{meta["commit"]}/{quote(rel, safe="/")}#L{start_line}-L{end_line}',
            "author_evidence": fields.get("证据等级", "未标注"),
            "author_grade": grade.group(1) if grade else None,
            "tags": tags, "author_cost_score": score, "author_ratio": ratio,
            "controversial": flags["dispute"],
            "author_flags": flags,
            "fields": {name: fields.get(name) for name in config.FIELD_NAMES},
            "source_links": config.URL.findall(fields.get("来源", "")),
            "evidence_state": evidence_state(raw),
            "raw": raw,
        }


def entries():
    meta = load_json("provenance.json")
    ranking_spec = load_json("ranking.json")
    result = [
        entry
        for path in _verified_chapter_paths(meta)
        for entry in _chapter_entries(path, meta, ranking_spec)
    ]
    ids = [e["id"] for e in result]
    if len(ids) != len(set(ids)):
        raise GuideError("SNAPSHOT_INTEGRITY", "章节条号重复，停止返回可能错配的依据。")
    return result


BRIEF_OMIT = {"raw", "fields"}


def brief(entry):
    out = {k: v for k, v in entry.items() if k not in BRIEF_OMIT}
    out["plain"] = entry["fields"]["说人话"]
    return out


def choose(all_entries, ids):
    index = {e["id"]: e for e in all_entries}
    missing = [i for i in ids if i not in index]
    if missing:
        raise GuideError("ENTRY_NOT_FOUND", "未找到条目：" + "、".join(missing))
    return [index[i] for i in dict.fromkeys(ids)]
