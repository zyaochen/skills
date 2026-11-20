"""Type: bars with a ceiling line. Use when the message is 'how far measured results are from the limit'."""
from _boot import out
from svgkit import Board

b = Board('GEMM 逐步调优：最好的手写版本仍差稠密峰值约四成',
          '条形是各版本实测吞吐；红色虚线是 BF16 稠密峰值，越靠近越好',
          src='来源：本 skill 示例数据；峰值取 H100 SXM BF16 稠密 989 TFLOPS')
rows = [('朴素三重循环', 12, 'gray'),
        ('共享内存分块', 180, 'blue'),
        ('寄存器分块', 420, 'blue'),
        ('warp 分块 + 双缓冲', 610, 'blue'),
        ('cuBLAS', 700, 'green', '参照')]
y = b.bars(40, 180, rows, w=760, label_w=230, unit=' TFLOPS', ref=(989, '稠密峰值 989'))
b.note(y + 32, '每一级分块都在提高数据复用；剩下的差距主要是搬运没有完全藏到计算后面。', fam='blue')
b.save(out('bars'))
