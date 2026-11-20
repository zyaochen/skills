"""Type: compare (before / after). Use when one change flips a mechanism; put the metric delta in tags."""
from _boot import out
from svgkit import Board

b = Board('H2D 拷贝换成锁页内存加异步流，搬运从关键路径上移走',
          '左边是改动前、右边是改动后；下方标签是同一负载复测的数字',
          src='来源：本 skill 示例数据；PCIe Gen5 x16 单向约 63 GB/s')
(lx, lw), (rx, rw) = b.cols(2, gap=96)
y1 = b.card(lx, 150, lw, '改前：可分页内存，同步拷贝', [
    '驱动先把数据复制到临时锁页缓冲，再走 DMA',
    'cudaMemcpy 返回前 GPU 什么都不做',
    '每个 batch 都在等主机'], fam='orange')
y2 = b.card(rx, 150, rw, '改后：锁页内存，异步流', [
    'DataLoader 设 pin_memory，拷贝直接走 DMA',
    'non_blocking 拷贝和上一步计算重叠',
    '下一 batch 在计算时已经到位'], fam='green')
y = max(y1, y2)
b.arrow([(lx + lw + 12, 150 + (y - 150) / 2), (rx - 12, 150 + (y - 150) / 2)], label='改两行')
tx = lx
for s, fam in [('H2D 21 → 47 GB/s', 'blue'), ('暴露的主机等待 38 → 4 ms', 'green'), ('step 210 → 176 ms', 'green')]:
    tx += b.tag(tx, y + 28, s, fam, 14) + 16
b.note(y + 84, '拷贝本身变快约一倍，更重要的是它被藏到了计算后面；时间账里 W_host 几乎归零。', fam='blue')
b.save(out('compare'))
