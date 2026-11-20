#!/usr/bin/env bash
# Self-test: run every offline script on a temp copy of assets/example_series and the gallery.
set -Eeuo pipefail
S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$(dirname "$S")"
TMP="$(mktemp -d)"
trap '[[ -n "${TMP:-}" && "$TMP" != "/" ]] && rm -rf "${TMP:?}"' EXIT
cp -R "$SKILL/assets/example_series/." "$TMP/"
export SERIES_ROOT="$TMP"
cd "$TMP"
fail() { echo "SELFTEST FAIL: $*"; exit 1; }

python3 "$S/init_series.py" "$TMP" >/dev/null
[[ -f spec/QUICK.md ]] || fail "QUICK.md not rendered"
grep -q "定天花板、测实际、复测" spec/QUICK.md || fail "QUICK.md terms not filled"
python3 "$SKILL/assets/example_series/drafts/01/figs/overview.py" >/dev/null
python3 "$SKILL/assets/example_series/drafts/01/figs/wait.py" >/dev/null
cp "$SKILL"/assets/example_series/drafts/01/figs/*.svg drafts/01/figs/
python3 "$S/normalize.py" 01 >/dev/null
python3 "$S/autofix.py" 01 >/dev/null
python3 "$S/build.py" 01 --quiet | grep -q "SUMMARY errors=0" || fail "build/lint 01 not clean"
python3 "$S/stats.py" 01 --strict >/dev/null || fail "stats 01 flagged"
python3 "$S/svgcheck.py" 01 >/dev/null || fail "svgcheck 01"
python3 "$S/build.py" 00 --quiet >/dev/null || fail "build hub"
python3 "$S/series_check.py" | grep -q "SERIES 示例系列: docs=3" || fail "series_check"
for role in $(python3 "$S/render_prompt.py" list | grep -v quick); do
  out="$(python3 "$S/render_prompt.py" "$role" 01 --segs s01 --extra x --have 1)"
  if grep -qE '\{[A-Z][A-Z0-9_]*\}' <<<"$out"; then fail "unfilled placeholder in $role"; fi
done

# negative cases: each must be caught
printf '%s' '<h1>第 3 章 · 坏例子</h1><p>瓶颈不是计算而是通信——见 {{C:01}}，用 **粗体**,然后进行优化。</p>' > drafts/01/seg/s03.xml
python3 "$S/build.py" 01 --quiet >/dev/null 2>&1 && fail "self-cite not caught"
printf '%s' '<h1>第 3 章 · 坏例子</h1><p>瓶颈不是计算而是通信——用 **粗体**,然后进行优化。</p>' > drafts/01/seg/s03.xml
out="$(python3 "$S/build.py" 01 --quiet || true)"
for k in "不是X而是Y" "破折号" "进行" "Markdown" "half-width"; do grep -q "$k" <<<"$out" || fail "lint missed $k"; done
rm drafts/01/seg/s03.xml
python3 -c "
import sys; sys.path.insert(0, '$S')
from svgkit import check_svg
bad = '<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 1200 500\"><text x=\"1190\" y=\"200\" font-size=\"9\" fill=\"#123456\">overflowing label</text></svg>'
issues = check_svg(bad)
need = ['missing title', 'missing 来源', 'off canvas', 'font 9px', 'off-palette']
miss = [n for n in need if not any(n in i for i in issues)]
sys.exit('missed: %s' % miss if miss else 0)
" || fail "check_svg missed issues"

python3 "$S/build.py" 01 --quiet >/dev/null
cp drafts/01/doc.xml "$TMP/pulled.xml"
python3 "$S/pull.py" 01 --from "$TMP/pulled.xml" --force >/dev/null || fail "pull"
python3 "$S/normalize.py" 01 >/dev/null
python3 "$S/build.py" 01 --quiet | grep -q "SUMMARY errors=0" || fail "rebuild after pull not clean"

python3 "$SKILL/assets/gallery/make_all.py" | grep -v ': OK$' && fail "gallery figure not clean" || true
echo "SELFTEST OK"
