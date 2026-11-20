"""Type: ledger (stacked bar). Use when the message is 'where the time/cost goes' and how a fix moves it."""
from _boot import out
from svgkit import Board

b = Board('把等待拆成账：overlap 之后通信不再暴露在关键路径上',
          '每条是一步训练的时间账，长度按毫秒等比；蓝色是有效计算，其余是暴露的等待',
          src='来源：本 skill 示例数据，演示时间账的画法')
before = [('计算', 620, 'blue'), ('等通信', 210, 'orange'), ('等主机', 90, 'gray'), ('空转', 80, 'red')]
after = [('计算', 620, 'blue'), ('等通信', 60, 'orange'), ('等主机', 90, 'gray'), ('空转', 50, 'red')]
y = b.stack(40, 170, 1120, before, unit=' ms', title='优化前：1000 ms / step')
y = b.stack(40, y + 64, 1120 * 820 / 1000, after, unit=' ms', title='bucket overlap 之后：820 ms / step')
b.note(y + 28, '通信从 210 ms 降到 60 ms：150 ms 藏到了反向计算后面。剩下的 90 ms 主机侧等待成了下一个瓶颈。',
       head='读法', fam='blue')
b.save(out('ledger'))
