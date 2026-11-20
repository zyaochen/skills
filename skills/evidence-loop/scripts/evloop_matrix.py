#!/usr/bin/env python3
"""跨模型评测矩阵入口：python3 evloop_matrix.py <plan|run> …（详见 --help）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evloop.matrix import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
