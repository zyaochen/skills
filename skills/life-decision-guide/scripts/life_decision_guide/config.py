"""检索规则的单一真源：路径、字面匹配规则、排序口径、输出措辞与错误目录。"""
import re
from pathlib import Path

SCHEMA_VERSION = 2

SKILL_ROOT = Path(__file__).resolve().parents[2]
REFERENCES = SKILL_ROOT / "references"
SOURCE_ROOT = REFERENCES / "source"
BOOK = SOURCE_ROOT / "book"
DOCS = SOURCE_ROOT / "docs"
README = SOURCE_ROOT / "README.md"

SECTION_HEADING = re.compile(r"^#\s+(\d+)\.\s+(.+)$", re.M)
ITEM_HEADING = re.compile(r"^###\s+(\d+)\.\s+(.+)$", re.M)
FIELD_NAMES = ("成本", "说人话", "收益", "证据等级", "来源", "备注")
FIELDS = re.compile(r"^-\s*(" + "|".join(FIELD_NAMES) + r")[：:]\s*(.*)$", re.M)
TAGS = re.compile(r"<!--\s*成本标签:\s*(.*?)\s*-->")
TAG_PAIRS = re.compile(r"(钱|时间|毅力|收益|口径)=([^\s]+)")
URL = re.compile(r"https?://[^\s）)，,；;。>\]]+")
DOC_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
DOC_TOOLING = {"docs/引用对照.md"}
DOC_RECORDS_PREFIX = "docs/核实记录/"
DOC_SCOPES = ("articles", "records", "all")

# 与上游 index.html 的 e.dispute / e.todo 判定逐字对齐。
AUTHOR_GRADE = re.compile(r"^\s*([ABC])")
AUTHOR_DISPUTE = re.compile(r"^争议")
AUTHOR_TODO = re.compile(r"待核实|TODO")
AUTHOR_TODO_FIELDS = ("来源", "收益", "备注", "成本")

GLOSSARY_HEADING = re.compile(r"^## 读懂数字[^\n]*\n([\s\S]*?)(?=^## )", re.M)
GLOSSARY_ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$")

METRICS = ("死亡率", "金钱", "时间", "自由")
GRADES = ("A", "B", "C")
RATIOS = ("极高", "高", "一般")
TAG_FILTERS = {"money": "钱", "time": "时间", "will": "毅力"}
TAG_VALUES = {"钱": ("0", "少", "多"), "时间": ("少", "中", "多"), "毅力": ("否", "些", "是")}

SOURCE_WARNING = re.compile(
    r"\bTODO\b|(?:待|尚未|未能|未)(?:核实|核对)"
    r"|待与[^\n。！？；]{1,100}(?:核实|核对)"
    r"|(?:未(?:能)?|无法)(?:找到|查到|获取|取得|访问|打开)[^\n。！？；]{0,40}(?:原文|原始文献|原始页面|原始来源)"
    r"|(?:原文|原始文献|原始页面|原始来源)[^\n。！？；]{0,30}(?:无法|不可|不能|未能)(?:访问|打开|获取|找到)",
    re.I,
)

COST_KEYS = ("钱", "时间", "毅力")
BENEFIT_LEVELS = ("大", "中", "小")
RATIO_ORDER = {"极高": 0, "高": 1, "一般": 2}
GRADE_ORDER = {"A": 0, "B": 1, "C": 2}

SEARCH_TITLE_WEIGHT = 6
SEARCH_LIMIT_DEFAULT = 8
SEARCH_LIMIT_RANGE = (1, 30)

NOTICES = {
    "search": "此结果仅用于定位，回答前须用 show 读取完整条目及备注；没有命中不等于全书无此主题。",
    "search_empty": "没有字面命中。换同义词、改用 --match any、放宽过滤条件，或用 list 按问题目录选章节后再搜；长文用 search-docs。",
    "search_docs": "长文逐行定位，只给命中行与所在小标题；回答前须读完整段落。长文和核实记录都不是条目，没有作者证据等级与成本标签；核实记录是作者的核对过程，不等于本次已核实。",
    "glossary": "术语解释取自原书 README 的「读懂数字」表，是原书的通俗说法，不是专业定义。",
    "show": "原文可能包含过时或绝对化说法，不能替代专业判断与当前官方核实。",
    "rank": "仅复现作者快照算法，非客观回报率；组与组之间不排序。同组仍可能有人群、时限、概率和基线风险差异。纳入排序不表示已独立核验；适用条件、安全禁忌和用户偏好优先。",
}

RESTORE_HINT = "从 references/provenance.json 记录的公开仓库与提交恢复同版本快照，不要用记忆补正文。"
NO_BOOK_FALLBACK = "说明无法读取书中依据；可另给明确标为通用建议的安全行动，但不能归因给书。"

ERRORS = {
    "INVALID_ARGUMENT": {
        "stage": "parse_args",
        "hints": ["用 --help 查看子命令与参数；条目 id 形如 2:9，可重复 --id。"],
        "fallback": "修正参数后重试。",
    },
    "ENTRY_NOT_FOUND": {
        "stage": "select",
        "hints": ["条号随版本变化，先用 search 或 list 取得本快照的实际 id；术语用 glossary 不带 --term 查看全表。"],
        "fallback": "改用 search 定位后再 show / rank。",
    },
    "SNAPSHOT_MISSING": {
        "stage": "load_corpus",
        "hints": [RESTORE_HINT],
        "fallback": NO_BOOK_FALLBACK,
    },
    "SNAPSHOT_INTEGRITY": {
        "stage": "load_corpus",
        "hints": [RESTORE_HINT, "不要修改 references/source/ 下的文件；哈希不一致时本工具拒绝返回依据。"],
        "fallback": NO_BOOK_FALLBACK,
    },
    "SNAPSHOT_UNREADABLE": {
        "stage": "load_corpus",
        "hints": ["检查 references/ 下的 JSON 与章节文件是否可读、编码是否为 UTF-8。", RESTORE_HINT],
        "fallback": NO_BOOK_FALLBACK,
    },
    "INTERNAL_ERROR": {
        "stage": "run",
        "hints": ["这是检索脚本自身的缺陷，不是用户输入问题；附上 error 字段报告给维护者。"],
        "fallback": "改按 references/routes.md 选章节并用文件搜索读取原文；仍无法读取时" + NO_BOOK_FALLBACK,
    },
}
