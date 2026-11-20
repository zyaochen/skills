"""Layout and house-style check for figures (wraps svgkit.check_svg).

    python3 svgcheck.py 19              # figures placed in drafts/19/seg ({{F:name}}) -> summary per figure
    python3 svgcheck.py 19 -v           # print every issue
    python3 svgcheck.py 19 --all        # every svg in drafts/19/figs, placed or not
    python3 svgcheck.py a.svg b.svg -v  # explicit files

E lines must be fixed. W lines are real in most cases (text overlapping, spilling out of a box, empty bands,
off-palette colours); fix them, or confirm on the rendered preview that it is a false positive and say so.
Exit code 1 when any E line exists.
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series import ddir, load  # noqa: E402
from svgkit import check_svg  # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    verbose = '-v' in sys.argv
    if not args:
        sys.exit(__doc__)
    if re.fullmatch(r'\d\d', args[0]):
        d = ddir(load(), args[0])
        placed = set()
        for p in glob.glob(os.path.join(d, 'seg', '*.xml')):
            placed |= set(re.findall(r'\{\{F:([A-Za-z0-9_\-]+)\}\}', open(p, encoding='utf-8').read()))
        files = sorted(glob.glob(os.path.join(d, 'figs', '*.svg')))
        if '--all' not in sys.argv:
            files = [f for f in files if os.path.basename(f)[:-4] in placed]
            missing = placed - {os.path.basename(f)[:-4] for f in files}
            for m in sorted(missing):
                print(f'{m}: E placed in seg but figs/{m}.svg is missing')
        label = args[0]
    else:
        files, label = args, 'files'
    bad = hard = 0
    for f in files:
        issues = check_svg(open(f, encoding='utf-8').read())
        if issues:
            bad += 1
            hard += any(i.startswith('E') for i in issues)
            print(f'{os.path.basename(f)[:-4]}: {len(issues)} issue(s)')
            if verbose:
                for s in issues[:15]:
                    print('   ', s)
    print(f'SVGCHECK {label}: {len(files)} figures, {bad} with issues, {hard} with E')
    sys.exit(1 if hard else 0)


if __name__ == '__main__':
    main()
