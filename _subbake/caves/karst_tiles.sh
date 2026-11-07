#!/bin/sh
# karst.geojsonl (from karst_build.py) -> karst_v1.pmtiles, layer "k", z3-12.
# Upload: rclone copyto karst_v1.pmtiles r2:bluishvoid-bg/under/karst_v1.pmtiles --s3-no-check-bucket
set -e
W=${1:-/Users/vvvaa/.claude/jobs/9395741e/tmp/subbake/caves/work}
tippecanoe -o "$W/karst_v1.pmtiles" -f -l k -Z3 -z12 \
  --detect-shared-borders --simplification=4 --coalesce-densest-as-needed \
  --drop-smallest-as-needed \
  --attribution='Weary &amp; Doctor 2014, USGS OFR 2014-1156 (public domain)' \
  -n "US karst (USGS OFR 2014-1156)" "$W/karst.geojsonl"
