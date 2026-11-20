#!/usr/bin/env python3
"""形式化检查器准备入口：python3 evloop_tlc.py <fetch|bundle|selftest|info> …（详见 --help）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evloop.tlc import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
