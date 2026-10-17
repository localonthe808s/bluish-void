"""Profile the McCoy CSVs: per city, rows, rows with coordinates, location_type, condition values, neighborhood and
address fill, and the observation/planted year range. Decides which cities bake and how.

  python3 -I _treesbake/profile.py <csvdir> > profile.json
"""
import csv, glob, json, os, sys
from collections import Counter

csv.field_size_limit(1 << 30)
out = {}
for p in sorted(glob.glob(os.path.join(sys.argv[1], '*_Final_2022-06-18.csv'))):
    key = os.path.basename(p).split('_Final')[0]
    n = xy = 0
    lt, cond, st, city = Counter(), Counter(), Counter(), Counter()
    nb, ad, nbv = 0, 0, Counter()
    yrs = Counter()
    with open(p, newline='', encoding='utf-8', errors='replace') as f:
        for r in csv.DictReader(f):
            n += 1
            try:
                la, lo = float(r['latitude_coordinate']), float(r['longitude_coordinate'])
                ok = -90 < la < 90 and -180 < lo < 180 and la != 0
            except (TypeError, ValueError, KeyError):
                ok = False
            if not ok:
                continue
            xy += 1
            lt[r.get('location_type')] += 1
            cond[r.get('condition')] += 1
            st[r.get('state')] += 1
            city[r.get('city')] += 1
            v = (r.get('neighborhood') or 'NA').strip()
            if v and v != 'NA':
                nb += 1; nbv[v] += 1
            a = (r.get('address') or 'NA').strip()
            if a and a != 'NA':
                ad += 1
            d = (r.get('most_recent_observation') or 'NA')[:4]
            if d.isdigit():
                yrs[int(d)] += 1
    out[key] = {'rows': n, 'xy': xy, 'location_type': dict(lt), 'condition': dict(cond.most_common(12)),
                'state': dict(st.most_common(3)), 'city': dict(city.most_common(5)), 'nbhd_rows': nb, 'nbhd_n': len(nbv),
                'nbhd_top': nbv.most_common(4), 'addr_rows': ad, 'obs_years': dict(sorted(yrs.items()))}
    print(key, n, xy, dict(lt), file=sys.stderr, flush=True)
json.dump(out, sys.stdout, indent=1)
