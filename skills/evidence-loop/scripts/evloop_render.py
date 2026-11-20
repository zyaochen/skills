#!/usr/bin/env python3
"""图 JSON 渲染入口：python3 evloop_render.py diagram.json [-o out.html]。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evloop.render import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
