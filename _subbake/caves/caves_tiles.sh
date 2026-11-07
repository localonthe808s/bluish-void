#!/bin/sh
# caves.geojsonl (osm_caves_build.py) -> cave_entrances_v1.pmtiles, layer "e", z2-12.
# Data (c) OpenStreetMap contributors, ODbL.
# Upload: rclone copyto cave_entrances_v1.pmtiles r2:bluishvoid-bg/under/cave_entrances_v1.pmtiles --s3-no-check-bucket
set -e
W=${1:-/Users/vvvaa/.claude/jobs/9395741e/tmp/subbake/caves/work}
tippecanoe -o "$W/cave_entrances_v1.pmtiles" -f -q -l e -Z2 -z12 -r1 \
  --drop-densest-as-needed --order-descending-by=show \
  --attribution='&copy; OpenStreetMap contributors (ODbL)' \
  -n "Cave entrances (OSM natural=cave_entrance)" "$W/caves.geojsonl"
