#!/bin/bash
# IDS damage areas -> one PMTiles archive (layer "ids"). props: c culprit, k kind (M mortality, D defoliation, X discoloration, O other),
# p percent of trees affected (mid), y survey year, a acres, h host. Run in the fetch.py OUTDIR:  bash build.sh OUT.pmtiles
set -e
python3 - <<'PY'
import json, glob
K = lambda t: 'M' if t.startswith('Mortality') else 'D' if t.startswith('Defoliation') else 'X' if 'Discolor' in t else 'O'
with open('ids_all.geojsonl', 'w') as fo:
    for p in sorted(glob.glob('ids_20*.geojsonl')):
        for l in open(p):
            f = json.loads(l); q = f['properties']; t = q.get('damage_type') or ''
            g = {'c': (q.get('dca_common_name') or 'unknown')[:40], 'k': K(t), 'p': q.get('percent_mid') or 0, 'y': q.get('survey_year'),
                 'a': round(q.get('acres') or 0, 1), 'h': (q.get('host_group') or q.get('host') or '')[:50]}
            if t.startswith('Defoliation'): g['d'] = t.replace('Defoliation ', '')[:30]
            fo.write(json.dumps({'type': 'Feature', 'geometry': f['geometry'], 'properties': g}, separators=(',', ':')) + '\n')
PY
tippecanoe -o "$1" -l ids -Z3 -z12 -P --read-parallel --no-tile-size-limit --coalesce-densest-as-needed --extend-zooms-if-still-dropping \
  --simplification=4 --detect-shared-borders --force ids_all.geojsonl 2>&1 | tail -3
ls -la "$1"
