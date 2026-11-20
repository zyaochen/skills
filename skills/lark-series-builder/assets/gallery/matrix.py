"""Type: matrix (comparison table inside a figure). Use for option selection; tint the recommended row."""
from _boot import out
from svgkit import Board

b = Board('选并行方案先看哪项等待最大，再挑消掉它代价最小的手段',
          '每行一种手段；绿色是本例的推荐选择',
          src='来源：本 skill 示例，选型矩阵的画法')
cols = [('手段', 210), ('消掉或藏起的等待', 300), ('代价', 300), ('什么时候选', 310)]
rows = [['数据并行 + 分桶 overlap', '梯度 all-reduce 的暴露部分', '每卡一份完整模型状态', '模型放得下一张卡时'],
        ['ZeRO-1 / ZeRO-2', '优化器状态和梯度的显存', '多一次 reduce-scatter 与 all-gather', '显存不够但不想动模型切分'],
        ['张量并行', '单卡放不下一层的问题', '每层 4 次 all-reduce，必须走 NVLink', '层很宽、机内 NVLink 充足'],
        ['流水线并行', '跨机带宽不足', '气泡 (p-1)/m，需要足够多的微批', '层数多、跨机带宽紧张']]
y = b.table(40, 150, cols, rows, hl={1: 'green'})
b.note(y + 28, '先用时间账确认最大的等待是显存还是通信，再选手段；不要一上来就叠满三种并行。', fam='blue')
b.save(out('matrix'))
