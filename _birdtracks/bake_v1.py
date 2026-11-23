#!/usr/bin/env python3
"""Bake European migratory bird tracks (Movebank / Zenodo, CC0 / CC BY) into compact binaries.

Usage (frozen v1 recipe, superseded by bake.py = v2): python3 -I bake_v1.py [key ...]   (no args = all species in SPECIES)

Per species writes out/<key>_v1.bin + out/<key>_v1.json, and out/tracks_v1.json for all baked species.
Binary layout (little-endian): per bird a header  uint32 bird_index, uint32 n_fixes
then n_fixes records of int32 t (s since 1990-01-01 UTC), int32 lat*1e4, int32 lon*1e4.
"""
import csv, gzip, json, math, os, struct, sys, datetime as dt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
OUT = os.path.join(HERE, 'out')
EPOCH = dt.datetime(1990, 1, 1)
csv.field_size_limit(10**8)

MAX_KMH = 150.0
STEP_H = 6.0          # never closer than 6 h
STILL_KM = 15.0       # ... and while the bird stays within this of the last kept fix
STILL_H = 24.0        # ... keep only one fix per day
MAX_BIRDS = 25
MAX_DAYS = 2.5 * 365.25
MIN_RANGE_KM = 700    # extent needed to count as "made a migration"
ARGOS_OK = {'3', '2', '1', 'G'}

MB = 'https://datarepository.movebank.org/handle/'
SPECIES = [
  dict(key='white_stork', max_kmd=700, common='White stork', sci='Ciconia ciconia', files=['gps.csv', 'argos.csv'],
       dataset='Data from: Study "MPIAB Argos white stork tracking (1991-2017)"', handle='10255/move.743'),
  dict(key='montagus_harrier', max_kmd=700, common="Montagu's harrier", sci='Circus pygargus', files=['argos.csv'],
       dataset='Data from: Migratory connectivity and population specific migration routes in a long-distance migratory bird', handle='10255/move.354'),
  dict(key='marsh_harrier', common='Western marsh harrier', sci='Circus aeruginosus', files=['gps-2018.csv.gz', 'gps-2019.csv.gz', 'gps-2020.csv.gz', 'gps-2021.csv.gz', 'gps-2022.csv.gz'],
       zenodo='22282061'),
  dict(key='egyptian_vulture', max_kmd=700, common='Egyptian vulture', sci='Neophron percnopterus', files=['gps.csv', 'argos.csv'],
       dataset='Data from: Satellite tracking a wide-ranging endangered vulture species to target conservation actions in the Middle East and East Africa', handle='10255/move.1006'),
  dict(key='rough_legged_buzzard', common='Rough-legged buzzard', sci='Buteo lagopus', files=['gps.csv'],
       dataset='Data from: Longer days enable higher diurnal activity for migratory birds [rough-legged buzzards]', handle='10255/move.1289'),
  dict(key='cuckoo', max_kmd=1200, common='Common cuckoo', sci='Cuculus canorus', files=['argos.csv', 'gps.csv'],
       dataset='Data from: Flying on their own wings: young and adult cuckoos respond similarly to long-distance displacement during migration', handle='10255/move.1073'),
  dict(key='crane', common='Common crane', sci='Grus grus', files=['gps.csv'],
       dataset='Data from: Study "GPS telemetry of Common Cranes, Sweden"', handle='10255/move.3261'),
  dict(key='white_fronted_goose', common='Greater white-fronted goose', sci='Anser albifrons', files=['gps.csv'],
       dataset='Data from: Towards a new understanding of migration timing: slower spring than autumn migration in geese reflects different decision rules for stopover use and departure', handle='10255/move.519'),
  dict(key='bewicks_swan', common="Bewick's swan", sci='Cygnus columbianus', files=['gps.csv'],
       dataset='Data from: Less is more: on-board lossy compression of accelerometer data increases biologging capacity', handle='10255/move.1017'),
  dict(key='spoonbill', common='Eurasian spoonbill', sci='Platalea leucorodia', files=['gps-2022.csv.gz', 'gps-2023.csv.gz', 'gps-2024.csv.gz', 'gps-2025.csv.gz'],
       zenodo='23103735'),
  dict(key='curlew', common='Eurasian curlew', sci='Numenius arquata', files=['gps.csv'],
       dataset='Data from: Migrating curlews on schedule: departure and arrival patterns of a long-distance migrant depend on time and breeding location rather than on wind conditions', handle='10255/move.1283'),
  dict(key='black_tailed_godwit', max_kmd=1800, common='Black-tailed godwit', sci='Limosa limosa', files=['argos.csv'],
       dataset='Data from: When Siberia came to The Netherlands: the response of continental black-tailed godwits to a rare spring weather event', handle='10255/move.446'),
  dict(key='lbb_gull', common='Lesser black-backed gull', sci='Larus fuscus', files=['gps-2020.csv.gz', 'gps-2021.csv.gz', 'gps-2022.csv.gz', 'gps-2023.csv.gz', 'gps-2024.csv.gz', 'gps-2025.csv.gz'],
       zenodo='22083230'),
  dict(key='caspian_tern', common='Caspian tern', sci='Hydroprogne caspia', files=['gps.csv'],
       dataset='Data from: Paternal transmission of migration knowledge in a long-distance bird migrant', handle='10255/move.1310'),
]


def ts(s):
    # 'YYYY-MM-DD HH:MM:SS(.fff)'
    try:
        d = dt.datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:19]))
    except (ValueError, IndexError):
        return None
    return (d - EPOCH).total_seconds()


def hav(lat1, lon1, lat2, lon2):
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(a)))


def opener(p):
    return gzip.open(p, 'rt', newline='', encoding='utf-8') if p.endswith('.gz') else open(p, newline='', encoding='utf-8')


def read_points(sp):
    birds = {}
    stats = dict(rows=0, invis=0, badlc=0, badcoord=0, taxon=0)
    for fn in sp['files']:
        p = os.path.join(CACHE, sp['key'], fn)
        with opener(p) as f:
            r = csv.DictReader(f)
            for row in r:
                stats['rows'] += 1
                if row.get('visible', 'true') == 'false' or row.get('manually-marked-outlier') == 'true' \
                        or row.get('algorithm-marked-outlier') == 'true' or row.get('import-marked-outlier') == 'true':
                    stats['invis'] += 1; continue
                tax = row.get('individual-taxon-canonical-name', '')
                if tax and tax.split()[:2] != sp['sci'].split()[:2]:
                    stats['taxon'] += 1; continue
                lc = row.get('argos:lc')
                if lc is not None and row.get('sensor-type', '').startswith('argos') and lc not in ARGOS_OK:
                    stats['badlc'] += 1; continue
                try:
                    lat = float(row['location-lat']); lon = float(row['location-long'])
                except (ValueError, TypeError):
                    stats['badcoord'] += 1; continue
                if not (math.isfinite(lat) and math.isfinite(lon)) or (lat == 0 and lon == 0) or abs(lat) > 90 or abs(lon) > 180:
                    stats['badcoord'] += 1; continue
                t = ts(row['timestamp'])
                if t is None:
                    continue
                ind = row.get('individual-local-identifier') or row.get('tag-local-identifier')
                birds.setdefault(ind, []).append((t, lat, lon))
    return birds, stats


def clean(pts, max_kmd=None):
    pts.sort()
    # dedupe identical timestamps
    out = []
    for p in pts:
        if out and p[0] - out[-1][0] < 60:
            continue
        out.append(p)
    pts = out
    if len(pts) < 3:
        return pts
    # spike pass: drop a fix that is fast both in and out
    keep = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = keep[-1], pts[i], pts[i + 1]
        v1 = hav(a[1], a[2], b[1], b[2]) / max((b[0] - a[0]) / 3600, 1 / 60)
        v2 = hav(b[1], b[2], c[1], c[2]) / max((c[0] - b[0]) / 3600, 1 / 60)
        if v1 > MAX_KMH and v2 > MAX_KMH:
            continue
        keep.append(b)
    keep.append(pts[-1])
    # forward pass with recovery after 3 consistent rejections
    def ok(a, p):
        dh = max((p[0] - a[0]) / 3600, 1 / 60)
        lim = MAX_KMH * dh
        if max_kmd:  # sustained cap for Argos sets: no more than max_kmd per day over long gaps
            lim = min(lim, max_kmd * max(dh / 24, 1.0))
        return hav(a[1], a[2], p[1], p[2]) <= lim
    acc = [keep[0]]; rej = []
    for p in keep[1:]:
        a = acc[-1]
        if ok(a, p):
            acc.append(p); rej = []
            continue
        rej.append(p)
        if len(rej) >= 3:
            if all(ok(rej[j], rej[j + 1]) for j in range(len(rej) - 1)):
                acc.extend(rej); rej = []
            else:
                rej = rej[1:]
    return despike(acc)


def despike(pts, km=250.0, ratio=0.35):
    # out-and-back spikes (typical Argos error, often slow enough to pass the speed test over long gaps):
    # b far from both neighbours while the neighbours sit close together
    changed = True
    while changed and len(pts) > 2:
        changed = False
        out = [pts[0]]
        i = 1
        while i < len(pts) - 1:
            a, b, c = out[-1], pts[i], pts[i + 1]
            ab = hav(a[1], a[2], b[1], b[2]); bc = hav(b[1], b[2], c[1], c[2]); ac = hav(a[1], a[2], c[1], c[2])
            if ab > km and bc > km and ac < ratio * min(ab, bc):
                changed = True
            else:
                out.append(b)
            i += 1
        out.append(pts[-1])
        pts = out
    return pts


def thin(pts):
    out = [pts[0]]
    for p in pts[1:]:
        a = out[-1]
        dh = (p[0] - a[0]) / 3600
        if dh < STEP_H:
            continue
        if dh < STILL_H and hav(a[1], a[2], p[1], p[2]) < STILL_KM:
            continue
        out.append(p)
    if pts[-1] is not out[-1] and (pts[-1][0] - out[-1][0]) / 3600 >= STEP_H:
        out.append(pts[-1])
    return out


def extent_km(pts):
    la = [p[1] for p in pts]; lo = [p[2] for p in pts]
    ex = [pts[int(np.argmin(la))], pts[int(np.argmax(la))], pts[int(np.argmin(lo))], pts[int(np.argmax(lo))]]
    return max(hav(a[1], a[2], b[1], b[2]) for a in ex for b in ex)


def path_km(pts):
    return sum(hav(pts[i][1], pts[i][2], pts[i + 1][1], pts[i + 1][2]) for i in range(len(pts) - 1))


def iso(t):
    return (EPOCH + dt.timedelta(seconds=t)).strftime('%Y-%m-%dT%H:%MZ')


def load_ref(sp):
    p = os.path.join(CACHE, sp['key'], 'ref.csv')
    ref = {}
    if not os.path.exists(p):
        return ref
    with open(p, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            aid = row.get('animal-id')
            if not aid:
                continue
            r = ref.setdefault(aid, {})
            for k in ('animal-sex', 'animal-nickname', 'animal-life-stage', 'manipulation-type', 'study-site'):
                v = (row.get(k) or '').strip()
                if v and k not in r:
                    r[k] = v
    return ref


def bake(sp):
    birds, stats = read_points(sp)
    ref = load_ref(sp)
    cands = []
    for ind, pts in birds.items():
        c = clean(pts, sp.get('max_kmd'))
        if len(c) < 10:
            continue
        t0 = c[0][0]
        c = [p for p in c if p[0] - t0 <= MAX_DAYS * 86400]
        th = thin(c)
        if len(th) < 10:
            continue
        ext = extent_km(th)
        days = (th[-1][0] - th[0][0]) / 86400
        cands.append(dict(ind=ind, pts=th, ext=ext, days=days, migr=ext >= MIN_RANGE_KM))
    cands.sort(key=lambda b: (not b['migr'], -b['days'] * (1 + b['ext'] / 3000)))
    chosen = cands[:MAX_BIRDS]
    chosen.sort(key=lambda b: b['pts'][0][0])
    buf = bytearray(); idx = []
    for i, b in enumerate(chosen):
        pts = b['pts']
        off = len(buf)
        buf += struct.pack('<II', i, len(pts))
        arr = np.array([(int(round(p[0])), int(round(p[1] * 1e4)), int(round(p[2] * 1e4))) for p in pts], dtype='<i4')
        buf += arr.tobytes()
        r = ref.get(b['ind'], {})
        sm = min(pts, key=lambda p: p[1])
        sex = {'m': 'm', 'f': 'f', 'male': 'm', 'female': 'f'}.get(r.get('animal-sex', '').lower())
        e = dict(id=i, label=r.get('animal-nickname') or b['ind'], local_id=b['ind'], sex=sex,
                 n_fixes=len(pts), offset=off, first=iso(pts[0][0]), last=iso(pts[-1][0]),
                 km=int(round(path_km(pts))), southmost=[round(sm[1], 3), round(sm[2], 3)],
                 migrated=b['migr'])
        if r.get('animal-life-stage'):
            e['life_stage'] = r['animal-life-stage']
        mt = r.get('manipulation-type', '')
        if mt and mt != 'none':
            e['manipulation'] = mt
        idx.append(e)
    with open(os.path.join(OUT, sp['key'] + '_v1.bin'), 'wb') as f:
        f.write(buf)
    with open(os.path.join(OUT, sp['key'] + '_v1.json'), 'w') as f:
        json.dump(dict(key=sp['key'], common=sp['common'], scientific=sp['sci'],
                       format='per bird: <II bird_index,n_fixes> then n_fixes x <iii t_s_since_1990-01-01Z, lat*1e4, lon*1e4>',
                       birds=idx), f, separators=(',', ':'))
    print('%-22s rows=%d birds_in=%d cand=%d migr=%d chosen=%d fixes=%d bytes=%d stats=%s' % (
        sp['key'], stats['rows'], len(birds), len(cands), sum(c['migr'] for c in cands), len(chosen),
        sum(e['n_fixes'] for e in idx), len(buf), stats), flush=True)
    return len(chosen)


if __name__ == '__main__':
    keys = sys.argv[1:]
    os.makedirs(OUT, exist_ok=True)
    meta = json.load(open(os.path.join(CACHE, 'meta.json')))
    built = {}
    tj = os.path.join(OUT, 'tracks_v1.json')
    if keys and os.path.exists(tj):
        built = {s['key']: s for s in json.load(open(tj))['species']}
    for sp in SPECIES:
        if keys and sp['key'] not in keys:
            continue
        n = bake(sp)
        m = meta[sp['key']]
        built[sp['key']] = dict(key=sp['key'], common=sp['common'], scientific=sp['sci'], dataset=m['dataset'],
                                citation=m['citation'], paper=m['paper'], doi_or_url=m['doi_or_url'], landing=m['landing'],
                                license=m['license'], license_url=m['license_url'], repository=m['repository'],
                                n_birds=n, file=sp['key'] + '_v1.bin', index=sp['key'] + '_v1.json')
    order = [sp['key'] for sp in SPECIES if sp['key'] in built]
    with open(tj, 'w') as f:
        json.dump(dict(built=dt.date.today().isoformat(),
                       format='bin: per bird <uint32 bird_index, uint32 n_fixes> then n_fixes x <int32 t (s since 1990-01-01Z), int32 lat*1e4, int32 lon*1e4>, little-endian; offsets in each index json',
                       thinning='outliers removed (Movebank visible/outlier flags, Argos LC 3/2/1 only, >150 km/h between fixes); >=6 h between kept fixes, and one per 24 h while within 15 km of the last kept fix; <=2.5 yr and <=25 birds per species',
                       species=[built[k] for k in order]), f, indent=1, ensure_ascii=False)
