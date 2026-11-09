#!/usr/bin/env python3
"""Montana — GWIC (MBMG Ground-Water Information Center) well logs, as republished by Montana DNRC's Water Sciences Bureau for
its Source Aquifer Explorer: ArcGIS FeatureServer 'Source_Aquifer_Explorer_Borehole_Data' (item 1bf6c5c552a34c7a9a96ab6e6f14d329):
layer 0 borehole points (~194k, gwicid/depth/elevation/date/location_accuracy) + table 6 lithology (~1.55M intervals, feet bgs,
driller text). GWIC's own downloads need a sign-in; this public view does not. Paged by OBJECTID (2000/page, sequential, cached).
site_name (= current owner) is never read. Intervals that fail DNRC's QA flag (from>to, negative) are dropped."""
import json, os, re, time, urllib.parse, urllib.request
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'mt')
FS = 'https://services2.arcgis.com/DRQySz3VhPgOv7Bo/arcgis/rest/services/Source_Aquifer_Explorer_Borehole_Data/FeatureServer/'
BOX = (44.2, 49.1, -116.2, -103.9)


def get(u, path):
    if os.path.exists(path) and os.path.getsize(path) > 0: return json.load(open(path))
    for a in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=180).read()
            d = json.loads(b.decode('utf-8'))
            if 'error' in d: raise ValueError(d['error'])
            tmp = path + '.part'; open(tmp, 'wb').write(b); os.replace(tmp, path); time.sleep(0.2); return d
        except Exception:
            time.sleep(5 * (a + 1))
    raise RuntimeError('failed ' + u)


def pages(layer, fields, geom):
    d = os.path.join(CACHE, 'L%d' % layer); os.makedirs(d, exist_ok=True)
    last, i = -1, 0
    while True:
        q = {'where': 'OBJECTID>%d' % last, 'outFields': 'OBJECTID,' + fields, 'orderByFields': 'OBJECTID',
             'resultRecordCount': 2000, 'returnGeometry': 'true' if geom else 'false', 'f': 'json'}
        if geom: q['outSR'] = 4326
        j = get(FS + '%d/query?' % layer + urllib.parse.urlencode(q), os.path.join(d, 'p%05d_%d.json' % (i, last)))
        fs = j.get('features') or []
        if not fs: return
        for f in fs: yield f
        last = fs[-1]['attributes']['OBJECTID']; i += 1
        if not j.get('exceededTransferLimit') and len(fs) < 2000: return


def wells():
    logs = {}
    for f in pages(6, 'gwicid,lith_from_ft,lith_to_ft,text,lith_qaqc_flag', False):
        a = f['attributes']
        if a.get('lith_qaqc_flag'): continue
        t = re.sub(r'\s+', ' ', a.get('text') or '').strip()[:120]
        if not t or a.get('gwicid') is None or a.get('lith_from_ft') is None: continue
        logs.setdefault(a['gwicid'], []).append((float(a['lith_from_ft']), None if a.get('lith_to_ft') is None else float(a['lith_to_ft']), t))
    seen = set()
    for f in pages(0, 'gwicid,total_depth_ft_bgs,date_completed,elevation_ft,location_accuracy', True):
        a, g = f['attributes'], f.get('geometry') or {}
        gid = a.get('gwicid')
        if gid is None or gid in seen or gid not in logs: continue
        lat, lon = g.get('y'), g.get('x')
        if lat is None or lon is None or not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]): continue
        seen.add(gid)
        lg = sorted(set(logs[gid]), key=lambda x: (x[0], x[1] if x[1] is not None else 1e9))
        y = (a.get('date_completed') or '')[:4]
        el = a.get('elevation_ft')
        yield {'id': 'mt:%d' % gid, 'lat': float(lat), 'lon': float(lon), 'elev_ft': None if el is None else round(el, 1),
               'depth_ft': a.get('total_depth_ft_bgs'), 'src': 'mt', 'name': 'GWIC %d' % gid,
               'date': y if re.match(r'^(18|19|20)\d\d$', y) else None,
               'log': [[round(x[0], 1), None if x[1] is None else round(x[1], 1), x[2]] for x in lg], 'loc': a.get('location_accuracy')}


if __name__ == '__main__':
    n = k = 0
    for w in wells(): n += 1; k += len(w['log'])
    print('wells', n, 'intervals', k)
