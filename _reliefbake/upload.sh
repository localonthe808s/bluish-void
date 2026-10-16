#!/bin/sh
# Push the baked relief tiles to R2 every 45 min while bake.py runs, then once more at the end.
# cover.json is rebuilt each pass, so the site picks up new coverage as it lands.
OUT=${1:-/Users/vvvaa/relief_bake/v1}
PAT=${2:-bake.py --out $OUT}      # bake_na.py runs pass "bake_na.py --out"
HERE=$(cd "$(dirname "$0")" && pwd)
push(){ python3 "$HERE/bake.py" --out "$OUT" --cover && rclone copy "$OUT" r2:bluishvoid-bg/relief/v1 --include "*.webp" --include "cover.json" \
  --s3-no-check-bucket --header-upload "Cache-Control: public, max-age=86400" --transfers 32 --checkers 32 --fast-list; date; }
sleep 600
while pgrep -f "$PAT" >/dev/null; do push; sleep 2700; done
push; echo FINAL
