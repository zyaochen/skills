#!/usr/bin/env bash
# Sequentially fetch Lark docs/wiki as markdown, retrying on rate limit.
# Usage: fetch_docs.sh <outdir> <doc-url-or-token>...
# Exit 1 if any document could not be fetched (listed at the end).
set -uo pipefail

[[ $# -ge 2 ]] || { echo "Usage: $0 <outdir> <doc-url-or-token>..." >&2; exit 1; }
outdir="$1"; shift
mkdir -p "$outdir"
export LARKSUITE_CLI_NO_UPDATE_NOTIFIER=1

failed=()
for doc in "$@"; do
  token="${doc%%\?*}"; token="${token##*/}"
  out="$outdir/$token.md"
  status="error"
  for attempt in 1 2 3 4; do
    status=$(lark-cli docs +fetch --doc "$doc" --as user --doc-format markdown 2>&1 | python3 -c '
import sys, json, re
raw = sys.stdin.read()
start = raw.find("{")
try:
    d = json.loads(raw[start:]) if start >= 0 else {}
except ValueError:
    d = {}
if d.get("ok"):
    c = d["data"]["document"]["content"]
    c = re.sub(r"<img[^>]*/?>", "", c)
    c = re.sub(r"\n{3,}", "\n\n", c)
    open(sys.argv[1], "w", encoding="utf-8").write(c)
    print("ok")
else:
    code = (d.get("error") or {}).get("code")
    print("ratelimit" if code == 99991400 else f"error:{code}")
' "$out")
    [[ "$status" == "ratelimit" ]] || break
    sleep $((attempt * 3))
  done
  if [[ "$status" == "ok" ]]; then
    printf 'ok    %8d bytes  %s\n' "$(wc -c < "$out")" "$token"
  else
    rm -f "$out"; failed+=("$token($status)"); printf 'FAIL  %s  %s\n' "$token" "$status"
  fi
  sleep 1
done

if [[ ${#failed[@]} -gt 0 ]]; then
  echo "Not fetched (3380004 = no permission): ${failed[*]}" >&2
  exit 1
fi
