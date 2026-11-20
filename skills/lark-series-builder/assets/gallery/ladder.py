"""Type: ladder (ordered levels). Use for hierarchies where one quantity drops level by level."""
from _boot import out
from svgkit import Board

b = Board('离计算单元每远一级，带宽就掉一个量级',
          '单卡单向带宽，GB/s；同样的字节数，越往下等得越久',
          src='来源：NVIDIA H100 规格页、PCIe 5.0 规范折算、ConnectX-7 规格页；均为单向口径')
rows = [('HBM3', 3350, 'blue', '片外显存'),
        ('NVLink4（单卡聚合）', 450, 'blue', '机内卡间'),
        ('PCIe Gen5 x16', 63, 'orange', '主机与网卡'),
        ('400G RDMA 网卡', 50, 'orange', '跨机')]
y = b.bars(40, 160, rows, w=700, label_w=250, unit=' GB/s', bh=34, gap=22)
cols = b.cols(2)
y2 = b.card(cols[0][0], y + 36, cols[0][1], '少搬字节', ['融合、复用、压缩，减少每一级上的流量'], fam='blue')
b.card(cols[1][0], y + 36, cols[1][1], '把搬运藏起来', ['异步、流水、overlap，让等待不在关键路径上'], fam='green')
b.save(out('ladder'))
