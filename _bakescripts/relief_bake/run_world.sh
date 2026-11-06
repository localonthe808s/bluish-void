#!/bin/zsh
# the world: run_world.sh <zmax> [zmin]: three pyramids in parallel, sharing the terrain-tile cache (bake_world.py). Resumable: run again to continue.
cd /Users/vvvaa/bluish-void/_reliefbake
export TT_CACHE=/Users/vvvaa/relief_bake/tt_cache
Z=${1:-8}
ZMIN=${2:-2}
for m in land sea depth; do
  nohup python3 bake_world.py --mode $m --out /Users/vvvaa/relief_bake/world/$m --zmin $ZMIN --zmax $Z --workers 6 >> /Users/vvvaa/relief_bake/world/$m.log 2>&1 &
done
wait
echo "ALL DONE $(date)" >> /Users/vvvaa/relief_bake/world/all.log
