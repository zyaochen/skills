"""Type: flow (numbered process). Use for a method, a pipeline or a decision procedure with 3-6 steps."""
from _boot import out
from svgkit import Board

b = Board('优化按五步走：每一步都留下可检查的产出',
          '编号是执行顺序；第 5 步复测的结论回到第 1 步，开始下一轮',
          src='来源：本 skill 示例，方法闭环的通用画法')
steps = [('定天花板', '用规格和账本算出理论时间'),
         ('测实际', '给出命令和指标名'),
         ('定位等待', '差距落在时间账的哪一项'),
         ('消除或隐藏', '手段加前后对比数字'),
         ('复测', '瓶颈转去了哪里', 'green')]
y = b.flow(40, 150, steps)
(x0, w0), (x4, w4) = b.cols(5, gap=44)[0], b.cols(5, gap=44)[4]
b.arrow([(x4 + w4 / 2, y + 4), (x4 + w4 / 2, y + 40), (x0 + w0 / 2, y + 40), (x0 + w0 / 2, y + 8)])
b.text(600, y + 34, '下一轮从新的瓶颈开始', 13, '#646A73', anchor='middle')
cols = b.cols(3)
ys = [b.card(x, y + 76, w, h, [t], fam='gray', white=True) for (x, w), (h, t) in zip(cols, [
    ('产出 1：一张时间账', '计算、等访存、等主机、等通信、空转各多少'),
    ('产出 2：一条证据', 'stall reason、时间线空隙或 busbw，能截图'),
    ('产出 3：前后两组数字', '同一命令、同一负载，复测可复现')])]
b.save(out('flow'))
