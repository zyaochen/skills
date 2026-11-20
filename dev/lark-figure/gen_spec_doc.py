"""Regenerate skills/lark-figure/references/spec.md and examples/*.json from each chart module's DOC.

    python3 dev/lark-figure/gen_spec_doc.py          # write
    python3 dev/lark-figure/gen_spec_doc.py --check  # exit 1 if anything is stale (used by tests)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(ROOT, 'skills', 'lark-figure')
sys.path.insert(0, os.path.join(SKILL, 'scripts'))

from lfig.canvas import T
from lfig.charts import CHARTS

HEAD = """# spec 字段参考

由 `dev/lark-figure/gen_spec_doc.py` 从各图型模块的 `DOC` 生成，不要手改。命令行等价：`figure.py example <type> --fields`。

## 所有图型通用

| 字段 | 必填 | 说明 |
|---|---|---|
| `type` | 是 | 下面任一图型名 |
| `title` | 是 | 一句判断，一行放得下（约 24 个汉字） |
| `subtitle` | 否 | 一句话说明怎么读这张图，最多两行 |
| `source` | 建议 | 以“来源：”开头；缺省写“来源：本文整理” |
| `callout` | 否 | `{text, label?:"结论", tone?:"contrast"}`，标题下方的结论横幅 |
| `legend` | 否 | `[{label, tone, style?: solid / dashed / line / dot}]` |

tone 取值：{tones}

"""


def render():
    out = [HEAD.replace('{tones}', '、'.join(f'`{k}`（{v}）' for k, v in T['tones'].items()))]
    for name, m in CHARTS.items():
        d = m.DOC
        out.append(f'## {name}\n\n{d["summary"]}\n\n| 字段 | 说明 |\n|---|---|\n')
        for k, v in d['fields'].items():
            out.append(f'| `{k}` | {v} |\n')
        out.append(f'\n样例：`examples/{name}.json`\n\n')
    return ''.join(out)


def examples():
    return {name: json.dumps(m.DOC['example'], ensure_ascii=False, indent=1) + '\n' for name, m in CHARTS.items()}


def main():
    check = '--check' in sys.argv
    stale = []
    targets = {os.path.join(SKILL, 'references', 'spec.md'): render()}
    targets.update({os.path.join(SKILL, 'examples', f'{n}.json'): s for n, s in examples().items()})
    for path, text in targets.items():
        cur = None
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                cur = f.read()
        if cur != text:
            stale.append(os.path.relpath(path, ROOT))
            if not check:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(text)
    if check and stale:
        sys.exit('stale (run gen_spec_doc.py): ' + ', '.join(stale))
    print('updated' if stale else 'up to date', *stale)


if __name__ == '__main__':
    main()
