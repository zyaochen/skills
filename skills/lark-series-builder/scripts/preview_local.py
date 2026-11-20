"""Render SVG figures to PNG locally (macOS Quick Look) so an agent can Read and judge them before publishing.

    python3 preview_local.py figs/a.svg figs/b.svg     # writes a.png next to each svg
    python3 preview_local.py 05                         # every figure placed in drafts/05/seg -> drafts/05/lpv/NAME.png
    python3 preview_local.py 05 overview wait           # only these figures

The local renderer uses a serif fallback font, so widths differ slightly from Lark; treat it as a layout check
(overlap, clipping, empty space, balance) and confirm on the published preview (publish.py writes drafts/NN/pv/).
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series import ddir, load  # noqa: E402

PX = 1600


def render(svg_path, png_path):
    if not shutil.which('qlmanage') or not shutil.which('sips'):
        sys.exit('qlmanage/sips not found (macOS only); use publish.py previews instead')
    s = open(svg_path, encoding='utf-8').read()
    s = re.sub(r'^\s*<\?xml[^>]*\?>\s*|^\s*<whiteboard[^>]*>\s*|\s*</whiteboard>\s*$', '', s)
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', s)
    w, h = (float(vb.group(1)), float(vb.group(2))) if vb else (1200.0, 600.0)
    # square viewport + default xMidYMid: content is centred, so a centre crop recovers it exactly
    s = re.sub(r'(<svg\b[^>]*?)\swidth="[^"]*"', r'\1', s, count=1)
    s = re.sub(r'(<svg\b[^>]*?)\sheight="[^"]*"', r'\1', s, count=1)
    s = s.replace('<svg ', '<svg width="720" height="720" ', 1)
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, 'f.svg')
        open(tmp, 'w', encoding='utf-8').write(s)
        subprocess.run(['qlmanage', '-t', '-s', str(PX), '-o', td, tmp], capture_output=True)
        out = tmp + '.png'
        if not os.path.exists(out):
            sys.exit(f'render failed: {svg_path}')
        crop = int(round(PX * min(1.0, h / w))) + 2
        subprocess.run(['sips', '-c', str(crop), str(PX), out, '--out', png_path], capture_output=True)
    return png_path


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if re.fullmatch(r'\d\d', args[0]):
        cfg = load()
        d = ddir(cfg, args[0])
        placed = []
        for p in sorted(glob.glob(os.path.join(d, 'seg', 's*.xml'))):
            placed += re.findall(r'\{\{F:([A-Za-z0-9_\-]+)\}\}', open(p, encoding='utf-8').read())
        names = args[1:] or placed
        os.makedirs(os.path.join(d, 'lpv'), exist_ok=True)
        jobs = [(os.path.join(d, 'figs', n + '.svg'), os.path.join(d, 'lpv', n + '.png')) for n in names]
    else:
        jobs = [(a, a[:-4] + '.png') for a in args]
    for svg, png in jobs:
        print(render(svg, png))


if __name__ == '__main__':
    main()
