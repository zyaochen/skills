"""Gallery bootstrap: put scripts/ on sys.path and give each exemplar its output path."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'scripts'))


def out(name):
    return os.path.join(HERE, name + '.svg')
