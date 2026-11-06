#!/bin/sh
# wait for the US bake, then the rest of North America, with its own uploader
while pgrep -f "bake.py --out /Users/vvvaa/relief_bake/v1" >/dev/null; do sleep 120; done
date; echo "US bake done; starting NA"
H=/Users/vvvaa/bluish-void/_reliefbake
P=/private/tmp/claude-501/-Users-vvvaa/28d6ef81-ce9e-4c6e-b98a-031f3699293c/scratchpad/physio/physio.shp
mkdir -p /Users/vvvaa/relief_bake/physio && cp ${P%.shp}.* /Users/vvvaa/relief_bake/physio/
nohup sh $H/upload.sh /Users/vvvaa/relief_bake/v1 "bake_na.py --out" > /Users/vvvaa/relief_bake/upload_na.log 2>&1 &
cd $H && python3 bake_na.py --out /Users/vvvaa/relief_bake/v1 --physio /Users/vvvaa/relief_bake/physio/physio.shp --workers 6
echo NA-EXIT $?
