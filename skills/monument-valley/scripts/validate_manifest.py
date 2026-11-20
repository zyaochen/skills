#!/usr/bin/env python3
"""离线、只读地检查山谷任务状态；不证明语义或远端资源真实性。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from valley_manifest import validate  # noqa: E402
from valley_manifest.cli import main  # noqa: E402

__all__ = ["main", "validate"]

if __name__ == "__main__":
    raise SystemExit(main())
