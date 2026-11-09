#!/usr/bin/env python3
"""Iowa GeoSam (Iowa Geological Survey, Univ. of Iowa): ~22,800 wells whose cuttings were logged by IGS geologists (strip
logs, flag log_strp=1). Locations + header from the public GeoSam ArcGIS FeatureServer; the interpreted log (start/end depth,
stratigraphic unit, primary/secondary lithology) from each well's public GeoSam page /well/<n>/geology/stratigraphy (HTML;
there is no bulk lithology download - driller's logs and strip logs themselves are scanned PDFs/JPGs, out of scope).
Pages are fetched sequentially (IA_SLEEP seconds apart, default 0.4) and the PARSED log is cached per well as JSON, so a
rerun is offline. IA_MAX=N stops after N wells (0 = all; the full crawl is ~22.8k pages, several hours, ~1.3 GB transfer).
Depths in feet. Coordinates: GeoSam lat/lon, mostly calculated from the PLSS legal description ('Calc. +/- 115 ft' ...),
some measured (GPS); 'loc' carries GeoSam's ll_acc text. Owner names are never requested."""
import html, json, os, re, sys, time, urllib.parse, urllib.request

UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'ia')
FS = 'https://services3.arcgis.com/kd9gaiUExYqUbnoq/arcgis/rest/services/GeoSam/FeatureServer/0/query'
PAGE = 'https://igs.iihr.uiowa.edu/igs/geosam/well/%d/geology/stratigraphy'
FIELDS = 'FID,wnumber,latitude,longitude,ll_acc,elevation,dpth_tot,dpth_well,drl_date,well_type,aquifer,log_strp'


def _get(u, timeout=90):
    for a in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read()
        except Exception:
            if a == 3: return None
            time.sleep(5 * (a + 1))


def points():
    os.makedirs(CACHE, exist_ok=True)
    off = 0
    while True:
        p = os.path.join(CACHE, 'pts_%06d.json' % off)
        if os.path.exists(p): d = json.load(open(p))
        else:
            q = urllib.parse.urlencode({'where': 'log_strp=1', 'outFields': FIELDS, 'orderByFields': 'FID', 'resultOffset': off,
                                        'resultRecordCount': 2000, 'returnGeometry': 'false', 'f': 'json'})
            b = _get(FS + '?' + q)
            if not b: raise RuntimeError('GeoSam FeatureServer query failed at offset %d' % off)
            d = json.loads(b)
            if 'features' not in d: raise RuntimeError(str(d)[:300])
            json.dump(d, open(p + '.part', 'w')); os.replace(p + '.part', p); time.sleep(0.5)
        for f in d['features']: yield f['attributes']
        if not d.get('exceededTransferLimit') and len(d['features']) < 2000: break
        off += len(d['features'])


def _num(s):
    m = re.search(r'-?\d+(?:\.\d+)?', s or '')
    return float(m.group(0)) if m else None


def parse(t):
    out = []
    for sec in re.split(r'<section class="row well">', t)[1:]:
        sec = re.sub(r'<script.*?</script>', '', sec, flags=re.S)
        s = html.unescape(re.sub(r'<[^>]+>', '|', sec)).replace('\xa0', ' ')
        cells = [c.strip() for c in re.split(r'\s*\|[\s|]*', s) if c.strip()]
        kv = {}
        for i, c in enumerate(cells[:-1]):
            k = c.rstrip(':')
            if k not in kv: kv[k] = cells[i + 1]
        top, bot = _num(kv.get('Start Depth')), _num(kv.get('End Depth'))
        if top is None: continue
        unit = kv.get('Unit') or kv.get('Formation') or ''
        if unit in ('System', 'Series', 'Unknown'): unit = ''
        lith = []
        for k, pk in (('Primary Lithology', None), ('Secondary Lithology', None)):
            v = kv.get(k, '')
            if v and v not in ('Unknown', 'Percent'): lith.append(v)
        out.append([top, bot, unit, lith])
    return out


def strat(w):
    d = os.path.join(CACHE, 'strat', '%03d' % (w % 1000)); p = os.path.join(d, '%d.json' % w)
    if os.path.exists(p): return json.load(open(p)), False
    b = _get(PAGE % w)
    if b is None: return None, True
    log = parse(b.decode('utf-8', 'replace'))
    os.makedirs(d, exist_ok=True)
    json.dump(log, open(p + '.part', 'w')); os.replace(p + '.part', p)
    return log, True


def wells():
    mx = int(os.environ.get('IA_MAX', '0') or 0); slp = float(os.environ.get('IA_SLEEP', '0.4'))
    seen = set(); n = 0
    for a in points():
        w = a.get('wnumber'); lat, lon = a.get('latitude'), a.get('longitude')
        if w is None or w in seen or lat is None or lon is None: continue
        seen.add(w)
        if not (40.3 <= lat <= 43.6 and -96.7 <= lon <= -90.1): continue
        log, fetched = strat(int(w))
        if fetched: time.sleep(slp)
        if not log: continue
        iv = []
        for top, bot, unit, lith in sorted(log, key=lambda x: (x[0], x[1] if x[1] is not None else 1e9)):
            d = '; '.join(l for l in lith if l != 'Unknown')
            if unit == 'Unknown': unit = ''
            if unit: d = (d + ' - ' + unit) if d else unit
            d = re.sub(r'\s+', ' ', d).strip()[:120]
            if not d: continue
            iv.append([float(top), float(bot) if bot is not None and bot >= top else None, d])
        if not iv: continue
        el = a.get('elevation'); el = float(el) if el and 400 <= el <= 1800 else None
        dep = a.get('dpth_tot') or a.get('dpth_well'); dep = float(dep) if dep and dep > 0 else None
        yr = None
        dd = a.get('drl_date')
        if isinstance(dd, (int, float)) and dd > -3e12:
            yr = time.strftime('%Y', time.gmtime(dd / 1000.0))
        elif isinstance(dd, str):
            m = re.search(r'(18|19|20)\d\d', dd); yr = m.group(0) if m else None
        yield {'id': 'ia:%d' % w, 'lat': float(lat), 'lon': float(lon), 'elev_ft': el, 'depth_ft': dep, 'src': 'ia', 'name': 'GeoSam W%d' % w,
               'date': yr, 'log': iv, 'loc': (a.get('ll_acc') or '').strip() or None, 'aq': (a.get('aquifer') or '').strip() or None}
        n += 1
        if mx and n >= mx: break
