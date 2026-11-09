#!/usr/bin/env python3
"""Western Long Island (Kings, Queens, Nassau): USGS data release "Geospatial Data Defining the Hydrogeologic Framework of
Kings, Queens, and Nassau Counties, Long Island, New York" (Finkelstein and others, 2024; ScienceBase 640b3c4bd34e254fd352d278),
file Framework_DataPoints: 1,715 hydrogeologic-unit top altitudes (ft, NAVD 88) picked at 657 boreholes from lithologic and/or
geophysical logs. Each borehole becomes a column of hydrogeologic units (Upper glacial ... Magothy, Raritan clay, Lloyd, bedrock).
Depths = land-surface altitude (USGS NWIS site file, alt_va) minus the unit's top altitude, so only boreholes with an NWIS
site number and altitude are kept (~645). USGS, public domain. These complement the NGWMN Long Island wells, whose logs carry
depth breaks but no words."""
import json, os, struct, time, urllib.request, zipfile
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'nyli')
ZIP = 'https://www.sciencebase.gov/catalog/file/get/640b3c4bd34e254fd352d278?f=__disk__62%2Fc6%2F9d%2F62c69d39c64201a9d1bc590967367b51105c7709'
NWIS = 'https://waterservices.usgs.gov/nwis/site/?format=rdb&siteOutput=expanded&sites='
ABOVE = 'Upper glacial aquifer and other deposits above the mapped units'


def get(u, path, timeout=120):
    if os.path.exists(path) and os.path.getsize(path) > 0: return open(path, 'rb').read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for a in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read()
            open(path + '.part', 'wb').write(b); os.replace(path + '.part', path); return b
        except Exception:
            time.sleep(3 * (a + 1))
    raise RuntimeError('download failed: ' + u)


def read_dbf(b):
    n, hl, rl = struct.unpack('<4xIHH', b[:12])
    fields, p = [], 32
    while b[p] != 0x0D:
        fields.append((b[p:p + 11].split(b'\0')[0].decode('ascii'), chr(b[p + 11]), b[p + 16])); p += 32
    for i in range(n):
        r = b[hl + i * rl: hl + (i + 1) * rl]
        if not r or r[:1] == b'*': continue
        o, d = 1, {}
        for name, t, ln in fields:
            v = r[o:o + ln].decode('latin-1', 'replace').strip(); o += ln
            if t in 'NF':
                try: v = float(v) if v else None
                except ValueError: v = None
            d[name] = v
        yield d


def nwis(sites):
    out = {}
    sites = sorted(sites)
    for i in range(0, len(sites), 100):
        chunk = sites[i:i + 100]
        t = get(NWIS + ','.join(chunk), os.path.join(CACHE, 'nwis_%03d.rdb' % (i // 100))).decode('utf-8', 'replace')
        hdr = None
        for line in t.splitlines():
            if not line or line.startswith('#'): continue
            f = line.split('\t')
            if hdr is None: hdr = f; continue
            if f[0].endswith('s') and f[0][:-1].isdigit(): continue  # rdb width row
            r = dict(zip(hdr, f))
            out[r.get('site_no')] = r
    return out


def fnum(s):
    try: return float(s)
    except (TypeError, ValueError): return None


def wells():
    z = zipfile.ZipFile(open_zip())
    rows = list(read_dbf(z.read('Framework_DataPoints.dbf')))
    by = {}
    for r in rows:
        s = (r.get('SITENO') or '').strip()
        if not s.isdigit(): continue
        by.setdefault(s, []).append(r)
    meta = nwis(by.keys())
    for s in sorted(by):
        m = meta.get(s) or {}
        alt = fnum(m.get('alt_va'))
        if alt is None: continue
        if (m.get('alt_datum_cd') or '').upper() == 'NGVD29': alt = round(alt - 1.1, 1)  # picks are NAVD 88; NGVD 29 sits ~1.1 ft higher here
        rs = sorted(by[s], key=lambda r: -(r['Elevation'] if r['Elevation'] is not None else -1e9))
        rs = [r for r in rs if r['Elevation'] is not None]
        if not rs: continue
        lat, lon = rs[0]['Lat'], rs[0]['Long']
        if lat is None or lon is None or not (40.4 <= lat <= 41.2 and -74.3 <= lon <= -73.3): continue
        tops = [(round(alt - r['Elevation'], 1), r['Geo_Layer'], r['DataType']) for r in rs]
        dep = fnum(m.get('well_depth_va')) or fnum(m.get('hole_depth_va'))
        log = []
        if tops[0][0] > 0.5: log.append([0.0, tops[0][0], ABOVE])
        for i, (top, unit, how) in enumerate(tops):
            top = max(top, 0.0)
            bot = tops[i + 1][0] if i + 1 < len(tops) else (dep if dep and dep > top else None)
            if bot is not None and bot <= top: continue
            log.append([top, bot, ('%s (top from %s log)' % (unit, how.lower().replace('lithology and geophysics', 'lithologic and geophysical')
                                                               .replace('lithology', 'lithologic').replace('geophysics', 'geophysical')))[:120]])
        if not log: continue
        yr = (m.get('construction_dt') or '')[:4]
        yield {'id': 'nyli:' + s, 'lat': float(lat), 'lon': float(lon), 'elev_ft': alt, 'depth_ft': dep, 'src': 'nyli',
               'name': ' '.join((rs[0].get('SiteName') or '').split()) or None, 'date': yr if yr.isdigit() else None, 'log': log}


def open_zip():
    p = os.path.join(CACHE, 'Framework_DataPoints.zip'); get(ZIP, p); return p


if __name__ == '__main__':
    n = 0
    for w in wells(): n += 1
    print('wells', n)
