#!/usr/bin/env python3
"""技能评测入口：python3 evloop_eval.py <validate|grade|benchmark> …（详见 --help）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evloop.evals import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
