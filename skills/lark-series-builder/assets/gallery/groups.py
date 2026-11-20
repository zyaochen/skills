"""Type: groups (grouped bars). Use for 'several workloads × two or three variants' on one shared scale."""
from _boot import out
from svgkit import Board

b = Board('新一代矩阵指令在长序列注意力上领先最多，短 GEMM 上差距不大',
          '每组是一种负载，条形是两代指令的实测吞吐（TFLOPS），共用一把刻度',
          src='来源：本 skill 示例数据，演示分组条形图的画法')
y = b.groups(40, 160, [('大 GEMM 8192³', [620, 1180]),
                       ('注意力 前向 8K', [480, 1010]),
                       ('小 GEMM 512³', [210, 260])],
             [('上一代 warpgroup 指令', 'gray'), ('新一代指令', 'blue')], unit=' TFLOPS', bh=24)
b.note(y + 36, '差距随负载变大而变大：小矩阵受发射和同步开销限制，新指令的吞吐优势用不上。', fam='blue')
b.save(out('groups'))
