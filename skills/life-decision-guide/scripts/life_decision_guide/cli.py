"""只读离线检索：定位并返回公开指南完整条目，不作诊疗或法律判断。"""
import argparse
import json
import platform
import sys
from collections import defaultdict
from urllib.parse import quote

from . import config
from .corpus import GuideError, brief, choose, doc_files, entries, load_json, verified_text


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise GuideError("INVALID_ARGUMENT", f"{self.prog}: {message}")


def list_chapters(all_entries):
    counts = defaultdict(int)
    for e in all_entries:
        counts[e["section"]] += 1
    return {
        "version": load_json("provenance.json")["commit"],
        "chapters": [dict(r, entry_count=counts[r["section"]]) for r in load_json("routes.json")],
    }


def _normalize_keywords(keywords):
    return [word.strip().casefold() for word in keywords or [] if word.strip()]


def _check_limit(limit):
    low, high = config.SEARCH_LIMIT_RANGE
    if not low <= limit <= high:
        raise GuideError("INVALID_ARGUMENT", f"limit 需在 {low} 到 {high} 之间。")


def _passes(entry, filters):
    tags = entry["tags"]
    checks = (
        (filters.get("sections"), entry["section"]),
        (filters.get("metric"), tags.get("口径")),
        (filters.get("grade"), entry["author_grade"]),
        (filters.get("ratio"), entry["author_ratio"]),
        *((filters.get(flag), tags.get(tag)) for flag, tag in config.TAG_FILTERS.items()),
    )
    if any(allowed and value not in allowed for allowed, value in checks):
        return False
    return all(entry["author_flags"][flag] for flag in ("dispute", "todo") if filters.get(flag))


def search(all_entries, keywords, filters=None, limit=config.SEARCH_LIMIT_DEFAULT, match="any"):
    filters = {k: v for k, v in (filters or {}).items() if v}
    keywords = _normalize_keywords(keywords)
    if not keywords and not filters:
        raise GuideError("INVALID_ARGUMENT", "请提供至少一个非空关键词，或至少一个过滤条件。")
    _check_limit(limit)
    required = len(keywords) if match == "all" else 1
    matches = []
    for entry in all_entries:
        if not _passes(entry, filters):
            continue
        title, raw = entry["title"].casefold(), entry["raw"].casefold()
        hits = [word for word in keywords if word in raw]
        if keywords and len(hits) < required:
            continue
        score = sum(config.SEARCH_TITLE_WEIGHT * (word in title) + 1 for word in hits)
        matches.append((score, entry))
    matches.sort(key=lambda pair: (-pair[0], pair[1]["section"], pair[1]["item"]))
    return {
        "matched_count": len(matches),
        "query": {"keywords": keywords, "match": match, "filters": filters},
        "notice": config.NOTICES["search" if matches else "search_empty"],
        "entries": [brief(e) for _, e in matches[:limit]],
    }


def search_docs(keywords, limit=config.SEARCH_LIMIT_DEFAULT, match="any", scope="articles"):
    keywords = _normalize_keywords(keywords)
    if not keywords:
        raise GuideError("INVALID_ARGUMENT", "请提供至少一个非空关键词。")
    _check_limit(limit)
    required = len(keywords) if match == "all" else 1
    meta, rels = doc_files(scope)
    hits = []
    for rel in rels:
        heading = None
        for number, line in enumerate((config.SOURCE_ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            found = config.DOC_HEADING.match(line)
            if found:
                heading = found.group(2).strip()
            matched = [word for word in keywords if word in line.casefold()]
            if len(matched) >= required:
                hits.append({
                    "file": rel, "line": number, "heading": heading, "text": line.strip(),
                    "url": f'{meta["repository"]}/blob/{meta["commit"]}/{quote(rel, safe="/")}#L{number}',
                    "_score": len(matched),
                })
    hits.sort(key=lambda h: (-h["_score"], h["file"], h["line"]))
    for hit in hits:
        del hit["_score"]
    return {
        "matched_count": len(hits),
        "scope": scope,
        "notice": config.NOTICES["search_docs" if hits else "search_empty"],
        "hits": hits[:limit],
    }


def glossary(terms=None):
    found = config.GLOSSARY_HEADING.search(verified_text("README.md"))
    if not found:
        raise GuideError("SNAPSHOT_INTEGRITY", "README 中缺少「读懂数字」术语表。")
    rows = []
    for line in found.group(1).splitlines():
        cells = config.GLOSSARY_ROW.match(line)
        if not cells or cells.group(1) == "术语" or set(cells.group(1)) <= {"-", " "}:
            continue
        aliases = [t.strip() for t in cells.group(1).split("、") if t.strip()]
        rows.append({"terms": aliases, "meaning": cells.group(2)})
    if terms:
        wanted = {t.strip().casefold() for t in terms if t.strip()}
        rows = [r for r in rows if wanted & {t.casefold() for t in r["terms"]}]
        missing = sorted(wanted - {t.casefold() for r in rows for t in r["terms"]})
    else:
        missing = []
    return {"notice": config.NOTICES["glossary"], "entries": rows, "not_found": missing}


def show(selected):
    return {"notice": config.NOTICES["show"], "entries": selected}


def rank(selected):
    groups = defaultdict(list)
    excluded = []
    for e in selected:
        pending = e["evidence_state"]["source_warning"]["status"] == "detected"
        if pending or e["author_ratio"] is None or "口径" not in e["tags"]:
            excluded.append(brief(e))
        else:
            groups[e["tags"]["口径"]].append(e)

    def order(e):
        grade = config.GRADE_ORDER.get(e["author_grade"], len(config.GRADE_ORDER))
        return (config.RATIO_ORDER[e["author_ratio"]], grade, e["section"], e["item"])

    return {
        "notice": config.NOTICES["rank"],
        "groups": [
            {"metric": metric, "entries": [brief(e) for e in sorted(items, key=order)]}
            for metric, items in groups.items()
        ],
        "excluded_pending_or_missing_tags": excluded,
    }


def build_parser():
    parser = JsonArgumentParser(prog="guide.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="显示章节及问题目录")
    p = sub.add_parser("search", help="条目定位：关键词 + 与上游检索页相同的过滤维度")
    p.add_argument("--keywords", nargs="+", default=[])
    p.add_argument("--match", choices=("any", "all"), default="any", help="any=任一关键词命中（默认），all=全部命中，同上游检索页")
    p.add_argument("--section", type=int, action="append", help="节号，可重复")
    p.add_argument("--metric", action="append", choices=config.METRICS, help="收益口径，可重复")
    p.add_argument("--grade", action="append", choices=config.GRADES, help="作者证据等级，可重复")
    p.add_argument("--ratio", action="append", choices=config.RATIOS, help="作者性价比档，可重复")
    for flag, tag in config.TAG_FILTERS.items():
        p.add_argument(f"--{flag}", action="append", choices=config.TAG_VALUES[tag], help=f"成本标签「{tag}」，可重复")
    p.add_argument("--dispute", action="store_true", help="只看备注以「争议」开头的条目")
    p.add_argument("--todo", action="store_true", help="只看作者标了待核实 / TODO 的条目")
    p.add_argument("--limit", type=int, default=config.SEARCH_LIMIT_DEFAULT)
    p = sub.add_parser("search-docs", help="在 docs/ 长文里逐行定位")
    p.add_argument("--keywords", nargs="+", required=True)
    p.add_argument("--match", choices=("any", "all"), default="any")
    p.add_argument("--scope", choices=config.DOC_SCOPES, default="articles", help="articles=公开长文（默认），records=核实记录，all=两者")
    p.add_argument("--limit", type=int, default=config.SEARCH_LIMIT_DEFAULT)
    p = sub.add_parser("glossary", help="原书术语表（HR、RR、95%% CI 等的通俗解释）")
    p.add_argument("--term", action="append", help="只查指定术语，可重复；不带则返回全表")
    for cmd, help_text in (("show", "完整读取条目"), ("rank", "按口径分组复现作者排序")):
        p = sub.add_parser(cmd, help=help_text)
        p.add_argument("--id", action="append", required=True, help="节:条，例如 2:9，可重复")
    return parser


def search_filters(args):
    filters = {
        "sections": args.section, "metric": args.metric, "grade": args.grade, "ratio": args.ratio,
        "dispute": args.dispute, "todo": args.todo,
    }
    filters.update({flag: getattr(args, flag) for flag in config.TAG_FILTERS})
    return filters


def dependency_summary():
    return {
        "python": platform.python_version(),
        "network": "not_used",
        "snapshot": "references/source",
    }


def failure(code, message):
    spec = config.ERRORS[code]
    return {
        "schema_version": config.SCHEMA_VERSION,
        "status": "error",
        "error": message,
        "errorCode": code,
        "stage": spec["stage"],
        "actionableHints": spec["hints"],
        "dependencySummary": dependency_summary(),
        "fallback": spec["fallback"],
    }


def run(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "search-docs":
        return search_docs(args.keywords, args.limit, args.match, args.scope)
    if args.command == "glossary":
        return glossary(args.term)
    data = entries()
    if args.command == "list":
        return list_chapters(data)
    if args.command == "search":
        return search(data, args.keywords, search_filters(args), args.limit, args.match)
    if args.command == "show":
        return show(choose(data, args.id))
    return rank(choose(data, args.id))


def main(argv=None):
    try:
        output = run(argv)
    except GuideError as exc:
        print(json.dumps(failure(exc.code, str(exc)), ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps(failure("SNAPSHOT_UNREADABLE", f"{type(exc).__name__}: {exc}"), ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps(failure("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}"), ensure_ascii=False), file=sys.stderr)
        return 2
    output = {"schema_version": config.SCHEMA_VERSION, "status": "ok", **output}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0
