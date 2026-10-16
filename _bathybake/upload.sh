#!/bin/sh
# Push the baked tiles to R2 every 45 min while bake.py runs, then once more at the end.
# cover.json is rebuilt each pass, so the site picks up new coverage as it lands.
OUT=${1:-/Users/vvvaa/bathy_bake/v1}
HERE=$(cd "$(dirname "$0")" && pwd)
push(){ python3 "$HERE/bake.py" --out "$OUT" --cover && rclone copy "$OUT" r2:bluishvoid-bg/bathy/v1 --include "*.webp" --include "cover.json" \
  --s3-no-check-bucket --header-upload "Cache-Control: public, max-age=86400" --transfers 32 --checkers 32 --fast-list; date; }
while pgrep -f "bake.py --out $OUT" >/dev/null; do push; sleep 2700; done
push; echo FINAL
