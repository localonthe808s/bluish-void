#!/usr/bin/env python3
"""Connecticut: USGS data release "Data release for depth to bedrock from Connecticut Water Resources Bulletins" (ver. 2.0,
Sept 2021; ScienceBase 5ff5caa7d34ea5387df033ba). 9,680 wells and test holes transcribed from the published tables of the
Connecticut Water Resources Bulletins (1966-80): location, land-surface altitude, hole depth, depth to bedrock, and the material
the hole ends in / the aquifer it is open to. A coarse two-part log: overburden down to bedrock, then the bedrock (or the
end-of-hole material when bedrock was not reached). Depths and altitudes in feet. USGS, public domain."""
import csv, io, os, time, urllib.request
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'ct')
URL = 'https://www.sciencebase.gov/catalog/file/get/5ff5caa7d34ea5387df033ba?f=__disk__0d%2Fb0%2Fd7%2F0db0d7088364d6d9b3a975526407f1eb493b34ce'
UNCONS = ('drift', 'sand', 'gravel', 'till', 'silt', 'clay', 'unconsolidated', 'hardpan', 'boulder', 'peat', 'muck', 'fill')


def get(u, path):
    if os.path.exists(path) and os.path.getsize(path) > 0: return open(path, 'rb').read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for a in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120).read()
            open(path + '.part', 'wb').write(b); os.replace(path + '.part', path); return b
        except Exception:
            time.sleep(3 * (a + 1))
    raise RuntimeError('download failed: ' + u)


def num(s):
    try: return float(str(s).strip())
    except ValueError: return None


def wells():
    raw = get(URL, os.path.join(CACHE, 'CTWRB_BedrockDepth.csv')).decode('latin-1')
    seen = set()
    for r in csv.DictReader(io.StringIO(raw)):
        lat, lon = num(r.get('LatDD')), num(r.get('LongDD'))
        if lat is None or lon is None or not (40.8 <= lat <= 42.2 and -74.0 <= lon <= -71.6): continue
        dep, bd = num(r.get('Depth_ft')), num(r.get('BedrockDepth_ft'))
        rem = (r.get('R_BedrockDepth_remark') or '').strip()
        mat = (r.get('R_Aquifer_or_EOH') or '').strip()
        if mat in ('-', ''): mat = ''
        hole = (r.get('HoleType') or '').strip().lower() or 'hole'
        refusal = (r.get('Refusal') or '').strip() == 'R' or mat.lower() == 'refusal'
        uncons = any(k in mat.lower() for k in UNCONS)
        log = []
        if bd is None and dep is None: continue
        if rem.startswith('>') or (bd is not None and dep is not None and bd >= dep and uncons and not refusal):
            # bedrock not reached: one interval, the whole hole in unconsolidated deposits
            bot = dep if dep is not None else bd
            if not bot or bot <= 0: continue
            d = 'Unconsolidated deposits; bedrock not reached'
            if mat and uncons: d += '; ends in ' + mat.lower()
            if refusal: d += '; refusal at bottom'
            log.append([0.0, bot, d])
        else:
            if bd is None: continue
            q = '' if rem in ('', '-') else ' (depth %s)' % {'F': 'from nearby data', '+': 'approximate', '+-': 'approximate',
                                                              '?': 'uncertain', '?R': 'uncertain', '<': 'or less', '<?': 'or less, uncertain'}.get(rem, 'approximate')
            if bd > 0:
                d = 'Unconsolidated deposits (overburden)'
                if mat and uncons: d = 'Unconsolidated deposits (overburden); open to ' + mat.lower()
                log.append([0.0, bd, d])
            if refusal:
                if log: log[-1][2] = log[-1][2] + '; refusal at bottom, probably bedrock' + q
                else: continue
            elif dep is not None and dep > bd:
                log.append([bd, dep, (mat if mat and not uncons else 'Bedrock') + q])
            elif log:
                log[-1][2] += '; bedrock at bottom' + q
            else:
                continue
        log = [[round(a, 1), None if b is None else round(b, 1), t[:120]] for a, b, t in log if b is None or b > a]
        if not log: continue
        name = (r.get('StationName') or '').strip() or None
        town = (r.get('Town') or '').strip()
        wid = 'ct:%s:%s' % (town.replace(' ', '_'), (name or '').replace(' ', '_'))
        if wid in seen:
            k = 2
            while '%s:%d' % (wid, k) in seen: k += 1
            wid = '%s:%d' % (wid, k)
        seen.add(wid)
        yield {'id': wid, 'lat': lat, 'lon': lon, 'elev_ft': num(r.get('Altitude_ft')), 'depth_ft': dep, 'src': 'ct',
               'name': ('%s %s (%s)' % (town, name, hole)) if name else None, 'date': None, 'log': log}


if __name__ == '__main__':
    n = 0
    for w in wells(): n += 1
    print('wells', n)
