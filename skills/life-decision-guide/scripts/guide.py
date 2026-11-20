#!/usr/bin/env python3
"""只读离线检索：定位并返回公开指南完整条目，不作诊疗或法律判断。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from life_decision_guide.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
