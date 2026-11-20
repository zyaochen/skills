"""Regenerate every gallery figure and print its layout check; add --png to render local previews."""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for py in sorted(glob.glob(os.path.join(HERE, '*.py'))):
    if os.path.basename(py).startswith(('_', 'make_all')):
        continue
    subprocess.run([sys.executable, py], cwd=HERE, check=True)
if '--png' in sys.argv:
    svgs = sorted(glob.glob(os.path.join(HERE, '*.svg')))
    subprocess.run([sys.executable, os.path.join(HERE, '..', '..', 'scripts', 'preview_local.py'), *svgs], check=True)
