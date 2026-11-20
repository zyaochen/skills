#!/usr/bin/env python3
"""山谷插画的确定性度量入口：色板覆盖、主角比例、接触表；不做审美判断。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from valley_manifest.analyze_cli import main  # noqa: E402

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
