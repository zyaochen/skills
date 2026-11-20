"""命令行：stdout 输出单个 JSON 结果，退出码 0 通过 / 1 未通过 / 2 无法读取。"""

import argparse
import json
from pathlib import Path

from . import config
from .checks import hints_for, validate


def build_result(phase, errors, unreadable=False, schema=None):
    passed = not errors
    return {
        "passed": passed,
        "phase": phase,
        "schemaVersion": schema,
        "errors": errors,
        "error": None if passed else ("无法读取 manifest" if unreadable else f"{len(errors)} 项检查未通过"),
        "stage": "read" if unreadable else "validate",
        "actionableHints": hints_for(errors),
        "fallback": None if passed else "修正 manifest 后重跑本检查；检查只核对记录，不替代在线回读与人工验收。",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线、只读地检查 valley_manifest.json；不访问网络、不写文件。")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--phase", choices=config.PHASES, default="draft")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result = build_result(args.phase, [f"读取或结构错误: {exc}"], unreadable=True)
        code = config.EXIT_UNREADABLE
    else:
        errors = validate(data, args.phase)
        schema = data.get("schema_version") if isinstance(data, dict) else None
        result = build_result(args.phase, errors, schema=schema)
        code = config.EXIT_FAILED if errors else config.EXIT_PASSED
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code
