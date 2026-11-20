"""Type: architecture / topology. Use cols() for a grid, tags for members, labelled arrows for links."""
from _boot import out
from svgkit import Board, width_of

b = Board('两台 8 卡节点：机内走 NVLink，跨机每张卡配一块 400G 网卡',
          '方框是节点，标签是 GPU 与网卡；箭头上标的是单向带宽',
          src='来源：NVIDIA DGX H100 用户指南；带宽为单向口径')
(lx, lw), (rx, rw) = b.cols(2, gap=160)
for x, w, name in ((lx, lw, '节点 A'), (rx, rw, '节点 B')):
    b.card(x, 150, w, name, [], fam='gray', h=300, white=True)
    b.card(x + 20, 200, w - 40, 'NVSwitch', ['每卡 450 GB/s'], fam='blue', size=13)
    cells = b.cols(4, x + 20, x + w - 20, gap=12)
    for row, (prefix, fam, ty) in enumerate([('GPU', 'blue', 300), ('GPU', 'blue', 340), ('NIC', 'orange', 400)]):
        for k, (cx, cw) in enumerate(cells):
            name = f'{prefix}{k + 4 * (row == 1)}'
            b.tag(cx + (cw - width_of(name, 13) - 20) / 2, ty, name, fam, 13)
b.text(lx + 24, 438, '另 4 块网卡省略', 12, '#646A73')
b.arrow([(lx + lw + 10, 300), (rx - 10, 300)], label='IB 8 × 50 GB/s')
b.arrow([(rx - 10, 340), (lx + lw + 10, 340)])
b.note(486, '机内带宽约是单卡跨机带宽的 9 倍：通信量大的切分（张量并行）放机内，跨机只放数据并行或流水线。',
       fam='blue')
b.save(out('arch'))
