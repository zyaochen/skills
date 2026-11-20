#!/usr/bin/env python3
"""evidence-loop 裁判入口：python3 evloop.py --home <run> <命令> …（详见 --help）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evloop.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
