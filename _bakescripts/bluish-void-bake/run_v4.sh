#!/bin/zsh
cd /Users/vvvaa/bluish-void/_maplab
OUT=/Users/vvvaa/bluish-void-bake/ink_v4
for z in 3 4 5 6; do python3 -u ink_pyramid_bake.py --level $z --out $OUT --port 9224 || echo "LEVEL $z FAILED"; done
python3 -u ink_pyramid_bake.py --level 7 --only-water --out $OUT --port 9224 || echo "LEVEL 7 FAILED"
# the resumable second pass, for any tile a dropped socket missed
for z in 5 6; do python3 -u ink_pyramid_bake.py --level $z --out $OUT --port 9224; done
python3 -u ink_pyramid_bake.py --level 7 --only-water --out $OUT --port 9224
echo ALL-LEVELS-DONE
