#!/usr/bin/env python3
"""Bake European migratory bird tracks (Movebank / Zenodo, CC0 / CC BY) into compact binaries -- version 2.

Usage: python3 -I bake.py [key ...]   (no args = all species in SPECIES)

Per species writes out/<key>_v2.bin + out/<key>_v2.json, and out/tracks_v2.json for all baked species.
Binary layout (little-endian, unchanged from v1): per bird a header  uint32 bird_index, uint32 n_fixes
then n_fixes records of int32 t (s since 1990-01-01 UTC), int32 lat*1e4, int32 lon*1e4.

v2 vs v1: a species can draw on several datasets ("sources"); each bird records the index of its source
in the species' `sources` list, and the species entry in tracks_v2.json lists every source with its own
citation and license.  Up to MAX_BIRDS per species, migrants first, picked round-robin across sources.
(bake_v1.py is the frozen v1 recipe.)
"""
import csv, glob, gzip, io, json, math, os, struct, sys, zipfile, datetime as dt
import site
sys.path.append(site.getusersitepackages())  # numpy lives in the user site, which -I hides
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
OUT = os.path.join(HERE, 'out')
VER = 'v2'
EPOCH = dt.datetime(1990, 1, 1)
csv.field_size_limit(10**8)

MAX_KMH = 150.0
STEP_H = 6.0          # never closer than 6 h
STILL_KM = 15.0       # ... and while the bird stays within this of the last kept fix
STILL_H = 48.0        # ... keep only one fix per this many hours (v1: 24)
MAX_BIRDS = 60
MAX_DAYS = 2.5 * 365.25
MIN_RANGE_KM = 700    # extent needed to count as "made a migration" (species may override: min_range)
MAX_FIX = 900         # per bird; above this the 6 h step doubles until it fits
FILL_TO = 10          # non-migrants only top a species up to this many birds
ARGOS_OK = {'3', '2', '1', 'G'}


def mb(handle, files, d='', **kw):
    return dict(handle=handle, files=files, dir=d, **kw)


def zen(rec, files, d='', **kw):
    return dict(zenodo=rec, files=files, dir=d, **kw)


GPS_YEARS = ['gps-*.csv.gz']   # INBO Zenodo packages: one gps file per year


SPECIES = [
  dict(key='white_stork', max_kmd=700, common='White stork', sci='Ciconia ciconia', sources=[
       mb('10255/move.743', ['gps.csv', 'argos.csv']),
       mb('10255/move.417', ['gps.csv.zip'], 'm417'),
       mb('10255/move.1339', ['gps.csv'], 'm1339')]),
  dict(key='montagus_harrier', max_kmd=700, common="Montagu's harrier", sci='Circus pygargus', sources=[
       mb('10255/move.354', ['argos.csv'], detour=True),  # sparse 2005-11 Argos: drop isolated detours
       zen('4971089', ['gps_raw.csv'], 'z4971089', reader='schlaich')]),
  dict(key='marsh_harrier', common='Western marsh harrier', sci='Circus aeruginosus', sources=[
       zen('22282061', GPS_YEARS),
       zen('10053583', GPS_YEARS, 'z10053583'),
       zen('10053658', GPS_YEARS, 'z10053658')]),
  dict(key='honey_buzzard', common='European honey buzzard', sci='Pernis apivorus', sources=[
       zen('4952397', ['processed.csv'], reader='vansteelant')]),
  dict(key='red_kite', common='Red kite', sci='Milvus milvus', sources=[
       mb('10255/move.1672', ['gps.csv'])]),
  dict(key='egyptian_vulture', max_kmd=700, common='Egyptian vulture', sci='Neophron percnopterus', sources=[
       mb('10255/move.1006', ['gps.csv', 'argos.csv'])]),
  dict(key='short_toed_eagle', common='Short-toed snake eagle', sci='Circaetus gallicus', sources=[
       mb('10255/move.483', ['gps.csv'])]),
  dict(key='steppe_eagle', common='Steppe eagle', sci='Aquila nipalensis', sources=[
       mb('10255/move.3548', ['gps.csv'])]),
  dict(key='lesser_spotted_eagle', max_kmd=700, common='Lesser spotted eagle', sci='Clanga pomarina', sources=[
       zen('4975315', ['meyburg.xlsx'], reader='meyburg')]),
  dict(key='rough_legged_buzzard', common='Rough-legged buzzard', sci='Buteo lagopus', sources=[
       mb('10255/move.1289', ['gps.csv'])]),
  dict(key='cuckoo', max_kmd=1200, common='Common cuckoo', sci='Cuculus canorus', sources=[
       mb('10255/move.1073', ['argos.csv', 'gps.csv'])]),
  dict(key='european_turtle_dove', common='European turtle dove', sci='Streptopelia turtur', sources=[
       zen('23097871', GPS_YEARS)]),
  dict(key='corn_crake', common='Corn crake', sci='Crex crex', sources=[
       zen('23097283', GPS_YEARS)]),
  dict(key='crane', common='Common crane', sci='Grus grus', sources=[
       mb('10255/move.3261', ['gps.csv']),
       mb('10255/move.3268', ['gps.csv'], 'm3268'),
       mb('10255/move.3257', ['gps.csv'], 'm3257')]),
  dict(key='demoiselle_crane', common='Demoiselle crane', sci='Anthropoides virgo', sources=[
       mb('10255/move.3259', ['gps.csv']),
       mb('10255/move.3258', ['gps.csv'], 'm3258'),
       mb('10255/move.3254', ['gps.csv'], 'm3254')]),
  dict(key='great_white_pelican', common='Great white pelican', sci='Pelecanus onocrotalus', sources=[
       mb('10255/move.945', ['gps.csv'])]),
  dict(key='white_fronted_goose', common='Greater white-fronted goose', sci='Anser albifrons', sources=[
       mb('10255/move.519', ['gps.csv']),
       mb('10255/move.851', ['gps.csv'], 'm851'),
       mb('10255/move.747', ['gps.csv', 'argos.csv'], 'm747')]),
  dict(key='taiga_bean_goose', common='Taiga bean goose', sci='Anser fabalis', sources=[
       mb('10255/move.1266', ['gps.csv'])]),
  dict(key='pink_footed_goose', max_kmd=1500, common='Pink-footed goose', sci='Anser brachyrhynchus', sources=[
       mb('10255/move.624', ['gps.csv', 'argos.csv'])]),
  dict(key='barnacle_goose', max_kmd=1500, common='Barnacle goose', sci='Branta leucopsis', sources=[
       mb('10255/move.383', ['argos.csv'])]),
  dict(key='greylag_goose', common='Greylag goose', sci='Anser anser', sources=[
       zen('17817498', ['data.zip'], reader='vantoor')]),
  dict(key='bewicks_swan', common="Bewick's swan", sci='Cygnus columbianus', sources=[
       mb('10255/move.1017', ['gps.csv'])]),
  dict(key='whooper_swan', common='Whooper swan', sci='Cygnus cygnus', sources=[
       mb('10255/move.1022', ['gps.csv'])]),
  dict(key='eurasian_teal', max_kmd=1500, common='Eurasian teal', sci='Anas crecca', sources=[
       mb('10255/move.1604', ['argos.csv'])]),
  dict(key='spoonbill', common='Eurasian spoonbill', sci='Platalea leucorodia', sources=[
       zen('23103735', GPS_YEARS)]),
  dict(key='curlew', common='Eurasian curlew', sci='Numenius arquata', sources=[
       mb('10255/move.1283', ['gps.csv']),
       zen('24005684', GPS_YEARS, 'z24005684')]),
  dict(key='black_tailed_godwit', max_kmd=1800, common='Black-tailed godwit', sci='Limosa limosa', sources=[
       mb('10255/move.446', ['argos.csv']),
       zen('5753619', ['adult_autumn.txt', 'adult_spring.txt', 'juv_autumn.txt', 'juv_spring.csv'], 'z5753619', reader='verhoeven')]),
  dict(key='gray_plover', max_kmd=1800, common='Gray plover', sci='Pluvialis squatarola', sources=[
       mb('10255/move.783', ['argos.csv'])]),
  dict(key='lbb_gull', common='Lesser black-backed gull', sci='Larus fuscus', sources=[
       zen('22083230', GPS_YEARS),
       zen('22273603', GPS_YEARS, 'z22273603')]),
  dict(key='mediterranean_gull', common='Mediterranean gull', sci='Ichthyaetus melanocephalus', sources=[
       zen('22108360', GPS_YEARS)]),
  dict(key='caspian_tern', common='Caspian tern', sci='Hydroprogne caspia', sources=[
       mb('10255/move.1310', ['gps.csv']),
       mb('10255/move.1332', ['gps.csv.zip'], 'm1332')]),
]


def ts(s):
    # 'YYYY-MM-DD HH:MM:SS(.fff)' or 'YYYY-MM-DDTHH:MM:SS(Z)'
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
    if p.endswith('.gz'):
        return gzip.open(p, 'rt', newline='', encoding='utf-8')
    if p.endswith('.zip'):
        z = zipfile.ZipFile(p)
        names = [n for n in z.namelist() if n.lower().endswith('.csv') and not n.startswith('__MACOSX')]
        assert len(names) == 1, (p, names)
        return io.TextIOWrapper(z.open(names[0]), encoding='utf-8', newline='')
    return open(p, newline='', encoding='utf-8')


def src_dir(sp, src):
    return os.path.join(CACHE, sp['key'], src.get('dir') or '')


def src_files(sp, src):
    d = src_dir(sp, src); out = []
    for fn in src['files']:
        out += sorted(glob.glob(os.path.join(d, fn))) if '*' in fn else [os.path.join(d, fn)]
    assert out, (sp['key'], src)
    return out


def add(birds, ind, t, lat, lon, stats):
    if not (math.isfinite(lat) and math.isfinite(lon)) or (lat == 0 and lon == 0) or abs(lat) > 90 or abs(lon) > 180:
        stats['badcoord'] += 1
        return
    if t is None:
        return
    birds.setdefault(ind, []).append((t, lat, lon))


def read_movebank(sp, src, birds, stats):
    for p in src_files(sp, src):
        with opener(p) as f:
            for row in csv.DictReader(f):
                stats['rows'] += 1
                if row.get('visible', 'true') == 'false' or row.get('manually-marked-outlier') == 'true' \
                        or row.get('algorithm-marked-outlier') == 'true' or row.get('import-marked-outlier') == 'true':
                    stats['invis'] += 1; continue
                tax = row.get('individual-taxon-canonical-name', '')
                if tax and not sp.get('taxon_any') and tax.split()[:2] != sp['sci'].split()[:2]:
                    stats['taxon'] += 1; continue
                lc = row.get('argos:lc')
                if lc is not None and row.get('sensor-type', '').startswith('argos') and lc not in ARGOS_OK:
                    stats['badlc'] += 1; continue
                st = row.get('sensor-type', '')
                if st and not (st.startswith('gps') or st.startswith('argos')):
                    stats['sensor'] = stats.get('sensor', 0) + 1; continue
                try:
                    lat = float(row['location-lat']); lon = float(row['location-long'])
                except (ValueError, TypeError):
                    stats['badcoord'] += 1; continue
                ind = row.get('individual-local-identifier') or row.get('tag-local-identifier')
                add(birds, ind, ts(row['timestamp']), lat, lon, stats)


def read_csv_cols(sp, src, birds, stats, idc, tc, latc, lonc, tparse=ts, delim=','):
    for p in src_files(sp, src):
        with opener(p) as f:
            for row in csv.DictReader(f, delimiter=delim):
                stats['rows'] += 1
                try:
                    lat = float(row[latc]); lon = float(row[lonc])
                except (ValueError, TypeError, KeyError):
                    stats['badcoord'] += 1; continue
                add(birds, row[idc], tparse(row[tc]), lat, lon, stats)


READERS = {}


def reader(name):
    def deco(fn):
        READERS[name] = fn
        return fn
    return deco


def read_points(sp, src):
    birds = {}
    stats = dict(rows=0, invis=0, badlc=0, badcoord=0, taxon=0)
    READERS.get(src.get('reader'), read_movebank)(sp, src, birds, stats)
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


def drop_detours(pts, km=1000.0, gap_d=2.0, ratio=0.75):
    # sparse Argos only: a lone fix with multi-day gaps on both sides that sends the track >1000 km off
    # course and back (e.g. a harrier 'in the Atlantic' between two land fixes) is a location error
    changed = True
    while changed and len(pts) > 2:
        changed = False
        for i in range(1, len(pts) - 1):
            a, b, c = pts[i - 1], pts[i], pts[i + 1]
            ab = hav(a[1], a[2], b[1], b[2]); bc = hav(b[1], b[2], c[1], c[2]); ac = hav(a[1], a[2], c[1], c[2])
            if ab > km and bc > km and b[0] - a[0] > gap_d * 86400 and c[0] - b[0] > gap_d * 86400 and ac < ratio * (ab + bc):
                del pts[i]; changed = True
                break
    return pts


def thin(pts, step_h=STEP_H):
    out = [pts[0]]
    for p in pts[1:]:
        a = out[-1]
        dh = (p[0] - a[0]) / 3600
        if dh < step_h:
            continue
        if dh < STILL_H and hav(a[1], a[2], p[1], p[2]) < STILL_KM:
            continue
        out.append(p)
    if pts[-1] is not out[-1] and (pts[-1][0] - out[-1][0]) / 3600 >= step_h:
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


def load_ref(sp, src):
    p = os.path.join(src_dir(sp, src), 'ref.csv')
    ref = {}
    if not os.path.exists(p):
        return ref
    with open(p, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            aid = row.get('animal-id')
            if not aid:
                continue
            r = ref.setdefault(aid, {})
            for k in ('animal-sex', 'animal-nickname', 'animal-life-stage', 'manipulation-type', 'manipulation-comments', 'study-site'):
                v = (row.get(k) or '').strip()
                if v and k not in r:
                    r[k] = v
    return ref


def candidates(sp):
    cands = []; seen = {}; dup = 0
    for si, src in enumerate(sp['sources']):
        birds, stats = read_points(sp, src)
        ref = load_ref(sp, src)
        for k, v in stats.pop('_ref', {}).items():
            ref.setdefault(k, {}).update(v)
        n0 = len(cands)
        for ind, pts in birds.items():
            c = clean(pts, src.get('max_kmd', sp.get('max_kmd')))
            if src.get('detour'):
                c = drop_detours(c)
            if len(c) < 10:
                continue
            t0 = c[0][0]
            c = [p for p in c if p[0] - t0 <= MAX_DAYS * 86400]
            th = thin(c)
            step = STEP_H
            while len(th) > MAX_FIX and step < 48:   # very busy birds (gulls, terns): coarser steps
                step *= 2
                th = thin(c, step)
            if len(th) < 10:
                continue
            # the same bird published in two datasets: keep the first copy
            t1 = th[-1][0]
            if any(min(t1, b1) - max(t0, a0) > 0.3 * (t1 - t0) for a0, b1 in seen.get(ind, [])):
                dup += 1
                continue
            seen.setdefault(ind, []).append((t0, t1))
            ext = extent_km(th)
            days = (t1 - t0) / 86400
            cover = len({int(p[0] // 86400) for p in c})  # days that actually carry a fix
            cands.append(dict(ind=ind, src=si, ref=ref.get(ind, {}), pts=th, ext=ext, days=days, cover=cover,
                              migr=ext >= sp.get('min_range', MIN_RANGE_KM), score=min(cover, days + 1) * (1 + ext / 3000)))
        print('   src %d %-16s rows=%d birds_in=%d cand=%d migr=%d stats=%s' % (
            si, src.get('handle') or 'zenodo:' + src['zenodo'], stats['rows'], len(birds), len(cands) - n0,
            sum(c['migr'] for c in cands[n0:]), stats), flush=True)
    if dup:
        print('   duplicates dropped: %d' % dup)
    return cands


def pick(cands):
    # migrants first; within a tier, round-robin over the sources so every population shows up.
    # Birds that never left home only fill in for species with few migrants (up to FILL_TO birds in all).
    chosen = []
    for tier in (True, False):
        cap = MAX_BIRDS if tier else max(len(chosen), FILL_TO)
        per = {}
        for c in sorted((c for c in cands if c['migr'] == tier), key=lambda c: -c['score']):
            per.setdefault(c['src'], []).append(c)
        while per and len(chosen) < cap:
            for s in sorted(per):
                if per[s] and len(chosen) < cap:
                    chosen.append(per[s].pop(0))
            per = {s: v for s, v in per.items() if v}
    return chosen


def bake(sp):
    print(sp['key'], flush=True)
    cands = candidates(sp)
    chosen = pick(cands)
    chosen.sort(key=lambda b: b['pts'][0][0])
    buf = bytearray(); idx = []
    for i, b in enumerate(chosen):
        pts = b['pts']
        off = len(buf)
        buf += struct.pack('<II', i, len(pts))
        arr = np.array([(int(round(p[0])), int(round(p[1] * 1e4)), int(round(p[2] * 1e4))) for p in pts], dtype='<i4')
        buf += arr.tobytes()
        r = b['ref']
        sm = min(pts, key=lambda p: p[1])
        sex = {'m': 'm', 'f': 'f', 'male': 'm', 'female': 'f'}.get(r.get('animal-sex', '').lower())
        e = dict(id=i, label=r.get('animal-nickname') or b['ind'], local_id=b['ind'], sex=sex,
                 n_fixes=len(pts), offset=off, first=iso(pts[0][0]), last=iso(pts[-1][0]),
                 km=int(round(path_km(pts))), southmost=[round(sm[1], 3), round(sm[2], 3)],
                 migrated=b['migr'], source=b['src'])
        if r.get('animal-life-stage'):
            e['life_stage'] = r['animal-life-stage']
        mt = r.get('manipulation-type', '')
        if mt and mt != 'none':
            e['manipulation'] = mt
            if r.get('manipulation-comments'):
                e['manipulation_note'] = r['manipulation-comments']
        idx.append(e)
    with open(os.path.join(OUT, '%s_%s.bin' % (sp['key'], VER)), 'wb') as f:
        f.write(buf)
    with open(os.path.join(OUT, '%s_%s.json' % (sp['key'], VER)), 'w') as f:
        json.dump(dict(key=sp['key'], common=sp['common'], scientific=sp['sci'],
                       format='per bird: <II bird_index,n_fixes> then n_fixes x <iii t_s_since_1990-01-01Z, lat*1e4, lon*1e4>; source = index into the species sources list in tracks_v2.json',
                       birds=idx), f, separators=(',', ':'))
    nsrc = [sum(1 for e in idx if e['source'] == s) for s in range(len(sp['sources']))]
    print('== %-22s cand=%d migr=%d chosen=%d (per source %s) fixes=%d bytes=%d' % (
        sp['key'], len(cands), sum(c['migr'] for c in cands), len(chosen), nsrc,
        sum(e['n_fixes'] for e in idx), len(buf)), flush=True)
    return len(chosen), nsrc


def src_id(src):
    return src.get('handle') or 'zenodo:' + src['zenodo']


# ---- readers for datasets that are not Movebank exports ------------------------------------------
@reader('vansteelant')   # honey buzzards: hourly migration fixes, id = <bird>.<journey>
def read_vansteelant(sp, src, birds, stats):
    for p in src_files(sp, src):
        with opener(p) as f:
            for row in csv.DictReader(f):
                stats['rows'] += 1
                add(birds, row['id'].split('.')[0], ts(row['datetime']), float(row['lat']), float(row['long']), stats)


@reader('schlaich')      # Montagu's harriers: id = <name>_<year>_<year> per season
def read_schlaich(sp, src, birds, stats):
    ref = stats.setdefault('_ref', {})
    for p in src_files(sp, src):
        with opener(p) as f:
            for row in csv.DictReader(f):
                stats['rows'] += 1
                ind = row['season'].rsplit('_', 2)[0]
                if ind not in ref:
                    ref[ind] = {'animal-sex': row['sex'], 'study-site': row['population']}
                try:
                    add(birds, ind, ts(row['date_time']), float(row['latitude']), float(row['longitude']), stats)
                except ValueError:
                    stats['badcoord'] += 1


def _num(x):
    return float(x.replace(',', '.'))


def _mdy(x):  # '7/19/2016' -> noon that day; '7/19/2016 3:51' -> that time
    day, _, hm = x.strip().partition(' ')
    m, d, y = (int(v) for v in day.split('/'))
    h, mi = (int(v) for v in hm.split(':')[:2]) if hm else (12, 0)
    return (dt.datetime(y, m, d, h, mi) - EPOCH).total_seconds()


@reader('verhoeven')     # black-tailed godwits (Verhoeven et al.): adult Argos, juvenile daily positions
def read_verhoeven(sp, src, birds, stats):
    ref = stats.setdefault('_ref', {})
    for p in src_files(sp, src):
        juv = os.path.basename(p).startswith('juv')
        with opener(p) as f:
            for row in csv.DictReader(f, delimiter=',' if p.endswith('.csv') else '\t'):
                stats['rows'] += 1
                if juv:
                    ind = row['Individual']; t = _mdy(row['timestamp'])
                    ref.setdefault(ind, {'animal-life-stage': 'juvenile (first migrations)'})
                else:
                    if row.get('visible') not in ('WAAR', 'TRUE', 'true'):
                        stats['invis'] += 1; continue
                    if row.get('argos:lc') not in ARGOS_OK:
                        stats['badlc'] += 1; continue
                    ind = row['individual-local-identifier']; t = ts(row['timestamp'])
                    ref.setdefault(ind, {'animal-life-stage': 'adult'})
                try:
                    add(birds, ind, t, _num(row['lat']), _num(row['lon']), stats)
                except ValueError:
                    stats['badcoord'] += 1


@reader('vantoor')       # greylag geese, Sweden: GPS table inside a zip with a metadata table
def read_vantoor(sp, src, birds, stats):
    ref = stats.setdefault('_ref', {})
    z = zipfile.ZipFile(src_files(sp, src)[0])
    for row in csv.DictReader(io.TextIOWrapper(z.open('250826_greylag_goose_metadata.csv'), encoding='utf-8')):
        ref[row['transmitter.id']] = {'animal-sex': row['sex'], 'animal-life-stage': row['age'], 'study-site': row['population']}
    for row in csv.DictReader(io.TextIOWrapper(z.open('250826_greylag_goose_gps_data.csv'), encoding='utf-8')):
        stats['rows'] += 1
        try:
            add(birds, row['transmitter.id'], ts(row['timestamp']), float(row['location.lat']), float(row['location.long']), stats)
        except ValueError:
            stats['badcoord'] += 1


@reader('meyburg')       # lesser spotted eagles: one xlsx sheet Bird / Origin / Age / Latitude / Longitude / Datetime (Excel serial)
def read_meyburg(sp, src, birds, stats):
    import xml.etree.ElementTree as ET
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    z = zipfile.ZipFile(src_files(sp, src)[0])
    sst = [''.join(t.text or '' for t in si.iter('{%s}t' % ns['x'])) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('x:si', ns)]
    ref = stats.setdefault('_ref', {})
    rows = ET.fromstring(z.read('xl/worksheets/sheet1.xml')).find('x:sheetData', ns)
    for r in list(rows)[1:]:
        v = {}
        for c in r:
            col = ''.join(ch for ch in c.get('r') if ch.isalpha()); x = c.find('x:v', ns)
            if x is None:
                continue
            v[col] = sst[int(x.text)] if c.get('t') == 's' else float(x.text)
        if not all(k in v for k in 'ABCDEF'):
            continue
        stats['rows'] += 1
        ind = v['A']
        if ind not in ref:
            ref[ind] = {'animal-life-stage': v['C'].lower(), 'study-site': {'GE': 'Germany', 'LA': 'Latvia'}.get(v['B'], v['B'])}
            if v['B'] == 'LA':   # Latvian nestlings, reared and released in Germany (Meyburg et al.)
                ref[ind].update({'manipulation-type': 'relocated',
                                 'manipulation-comments': 'translocated as a nestling from Latvia (~940 km), reared and released in Germany'})
        add(birds, ind, (dt.datetime(1899, 12, 30) + dt.timedelta(days=v['F']) - EPOCH).total_seconds(), v['D'], v['E'], stats)


if __name__ == '__main__':
    keys = sys.argv[1:]
    os.makedirs(OUT, exist_ok=True)
    meta = json.load(open(os.path.join(CACHE, 'meta_v2.json')))
    built = {}
    tj = os.path.join(OUT, 'tracks_%s.json' % VER)
    if keys and os.path.exists(tj):
        built = {s['key']: s for s in json.load(open(tj))['species']}
    for sp in SPECIES:
        if keys and sp['key'] not in keys:
            continue
        n, nsrc = bake(sp)
        srcs = []
        for src, k in zip(sp['sources'], nsrc):
            m = dict(meta[src_id(src)]); m['n_birds'] = k
            srcs.append(m)
        used = [m for m in srcs if m['n_birds']] or srcs
        m0 = max(used, key=lambda m: m['n_birds'])  # the main source fills the v1-style flat fields
        lic = sorted({m['license'] for m in used})
        built[sp['key']] = dict(key=sp['key'], common=sp['common'], scientific=sp['sci'], dataset=m0['dataset'],
                                citation=m0['citation'], paper=m0['paper'], doi_or_url=m0['doi_or_url'], landing=m0['landing'],
                                license=m0['license'], license_url=m0['license_url'], repository=m0['repository'],
                                licenses=lic, sources=srcs,
                                n_birds=n, file='%s_%s.bin' % (sp['key'], VER), index='%s_%s.json' % (sp['key'], VER))
    order = [sp['key'] for sp in SPECIES if sp['key'] in built]
    with open(tj, 'w') as f:
        json.dump(dict(built=dt.date.today().isoformat(), version=VER,
                       format='bin: per bird <uint32 bird_index, uint32 n_fixes> then n_fixes x <int32 t (s since 1990-01-01Z), int32 lat*1e4, int32 lon*1e4>, little-endian; offsets in each index json; each bird\'s "source" indexes that species\' "sources" list (every source carries its own citation and license; the flat dataset/citation/license fields describe the source most birds come from)',
                       thinning='outliers removed (Movebank visible/outlier flags, Argos LC 3/2/1 only, >150 km/h between fixes, out-and-back spikes); >=%g h between kept fixes (12/24 h for birds that would exceed %d fixes), and one per %g h while within %g km of the last kept fix; <=2.5 yr and <=%d birds per species, migrants (>=%d km extent) first, round-robin across sources' % (STEP_H, MAX_FIX, STILL_H, STILL_KM, MAX_BIRDS, MIN_RANGE_KM),
                       species=[built[k] for k in order]), f, indent=1, ensure_ascii=False)
