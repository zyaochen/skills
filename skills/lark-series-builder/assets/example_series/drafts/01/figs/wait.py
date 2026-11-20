"""Example figure for the example series (lanes type)."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..', 'scripts'))
from svgkit import Board  # noqa: E402

b = Board('同步拷贝时，每个 batch 前 GPU 都空等一段', '横轴是时间，单位为示意刻度；橙色是拷贝，蓝色是计算',
          src='来源：本示例整理，示意图')
y = b.lanes(40, 150, [('拷贝 stream', [(0, 30, 'orange', 'H2D'), (100, 130, 'orange', 'H2D')]),
                      ('计算 stream', [(30, 100, 'blue', '计算'), (130, 200, 'blue', '计算')])], t_max=200, ticks=4)
b.note(y + 28, '拷贝和计算串行：两段 H2D 都暴露在关键路径上。', fam='orange')
b.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wait.svg'))
