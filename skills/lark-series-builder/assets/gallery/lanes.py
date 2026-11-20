"""Type: lanes (timeline). Use for overlap, pipelining, bubbles, serialisation between streams or devices."""
from _boot import out
from svgkit import Board

b = Board('把 all-reduce 切成桶，通信就能和反向计算重叠',
          '横轴是时间（ms），每条泳道是一个 CUDA stream；橙色块露在计算之外的部分才算等待',
          src='来源：本 skill 示例数据，演示 overlap 的画法')
b.text(40, 160, '串行：反向算完才开始通信，step 180 ms', 15, bold=True)
y = b.lanes(40, 180, [('计算 stream', [(0, 40, 'blue', '前向'), (40, 120, 'blue', '反向')]),
                      ('通信 stream', [(120, 180, 'orange', 'all-reduce 全部梯度')])], t_max=200, ticks=0)
b.text(40, y + 44, '分桶 overlap：每个桶算完就发，step 135 ms', 15, bold=True)
y = b.lanes(40, y + 64, [('计算 stream', [(0, 40, 'blue', '前向'), (40, 120, 'blue', '反向')]),
                         ('通信 stream', [(60, 90, 'orange', '桶 1'), (90, 120, 'orange', '桶 2'),
                                          (120, 135, 'orange', '桶 3')])], t_max=200, unit=' ms')
b.note(y + 24, '暴露的通信从 60 ms 降到 15 ms：只剩最后一个桶露在反向计算之后。', fam='green')
b.save(out('lanes'))
