"""Example figure for the example series (compare type)."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..', 'scripts'))
from svgkit import Board  # noqa: E402

b = Board('锁页内存省掉一次复制，异步拷贝才真正和计算重叠', '左边是可分页内存的路径，右边是锁页内存的路径',
          src='来源：NVIDIA CUDA C++ Best Practices Guide；PyTorch pin_memory 教程')
(lx, lw), (rx, rw) = b.cols(2, gap=96)
y1 = b.card(lx, 150, lw, '可分页内存', ['驱动先复制到临时锁页缓冲', '再由 DMA 拷到显存，两段串行'], fam='orange')
y2 = b.card(rx, 150, rw, '锁页内存', ['DMA 直接读主机内存', '可以和计算在不同 stream 上重叠'], fam='green')
y = max(y1, y2)
b.arrow([(lx + lw + 12, (150 + y) / 2), (rx - 12, (150 + y) / 2)], label='pin_memory')
b.note(y + 32, 'GPU 等主机拷贝的时间从关键路径上移走。', fam='blue')
b.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'overview.svg'))
