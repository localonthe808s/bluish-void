#!/usr/bin/env python3
"""Bake what the great observatories are doing, for the SPACE tab's OBSERVATORIES NOW
row and EARTH VIEW (user 2026-09-23: "build all of it").

None of these sources can be read by the page directly -- STScI's schedule files and
JPL Horizons send no CORS headers -- so a scheduled Action runs this and commits small
files the page reads from its own origin.

Writes:
  observatories.json        Webb's published observing schedule (the newest week),
                            what Hubble and Webb observed in the last ~2 days (NASA MAST),
                            Parker Solar Probe's distance/speed series + perihelia
  _solarlab/_roman.js       Roman's delivered trajectory, launch -> end of the current
                            Horizons solution (same schema the EARTH VIEW already reads)
  _solarlab/_l2craft.js     JWST (-170) and Euclid (-680) geocentric ecliptic positions,
                            6-hourly, a week back to four months ahead

Every source is US-government / public domain (NASA, STScI for NASA, JPL). MAST's own
quick-look JPEGs were tried and dropped: they are raw detector frames (noise, chip gaps,
stripes) and read as broken next to the event cards' renders.

usage: build_observatories.py
"""
import datetime as dt, json, math, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {'User-Agent': 'bluishvoid-bake (+https://bluishvoid.com)'}
NOW = dt.datetime.now(dt.timezone.utc)


def get(url, data=None, timeout=120, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(10 * (i + 1))


def ms(d): return int(d.timestamp() * 1000)


# ── JPL HORIZONS ─────────────────────────────────────────────────────────────
def horizons(cmd, center, start, stop, step):
    """[(datetime, x, y, z, vx, vy, vz)] ecliptic J2000, km and km/s; or raises with
    Horizons' own message (it names the end of a spacecraft's solution)."""
    p = {'format': 'json', 'COMMAND': "'%s'" % cmd, 'OBJ_DATA': 'NO', 'MAKE_EPHEM': 'YES',
         'EPHEM_TYPE': 'VECTORS', 'CENTER': "'%s'" % center, 'START_TIME': "'%s'" % start,
         'STOP_TIME': "'%s'" % stop, 'STEP_SIZE': "'%s'" % step, 'REF_PLANE': 'ECLIPTIC',
         'VEC_TABLE': '2', 'OUT_UNITS': 'KM-S', 'CSV_FORMAT': 'YES', 'TIME_TYPE': 'UT'}
    t = json.loads(get('https://ssd.jpl.nasa.gov/api/horizons.api?' + urllib.parse.urlencode(p)))['result']
    s, e = t.find('$$SOE'), t.find('$$EOE')
    if s < 0: raise RuntimeError(t[-600:])
    out = []
    for line in t[s + 5:e].strip().split('\n'):
        c = [x.strip() for x in line.split(',')]
        when = dt.datetime.strptime(c[1].replace('A.D. ', '')[:20], '%Y-%b-%d %H:%M:%S').replace(tzinfo=dt.timezone.utc)
        out.append((when,) + tuple(float(v) for v in c[2:8]))
    return out


def solution_end(cmd, center, start):
    """Horizons refuses past a spacecraft's delivered solution and says where it ends."""
    try:
        horizons(cmd, center, start, (NOW + dt.timedelta(days=400)).strftime('%Y-%m-%d'), '10d')
        return NOW + dt.timedelta(days=400)
    except RuntimeError as err:
        m = re.search(r'after A\.D\. (\d{4}-[A-Z]{3}-\d{2} \d{2}:\d{2})', str(err))
        if not m: raise
        return dt.datetime.strptime(m.group(1).title(), '%Y-%b-%d %H:%M').replace(tzinfo=dt.timezone.utc)


def lon_km(r):
    x, y = r[1], r[2]
    return [round(math.degrees(math.atan2(y, x)) % 360, 3), round(math.hypot(x, y), 1)]


def bake_roman():
    """Same schema as the 09-07 hand bake: hourly [ecliptic lon deg, in-plane range km]
    from the first whole hour after launch to the end of the current solution."""
    launch = dt.datetime(2026, 8, 30, 11, 26, 4, tzinfo=dt.timezone.utc)
    t0 = dt.datetime(2026, 8, 30, 12, 0, tzinfo=dt.timezone.utc)
    end = solution_end('-211', '500@399', t0.strftime('%Y-%m-%d %H:%M')) - dt.timedelta(hours=1)
    rows = horizons('-211', '500@399', t0.strftime('%Y-%m-%d %H:%M'), end.strftime('%Y-%m-%d %H:%M'), '1h')
    R = {'src': 'JPL Horizons, target -211, geocentric ecliptic vectors', 'launch': ms(launch),
         'built': NOW.strftime('%Y-%m-%d'), 'solution_end': ms(rows[-1][0]),
         't0': ms(rows[0][0]), 'step': 3600000, 'n': len(rows), 'p': [lon_km(r) for r in rows]}
    (ROOT / '_solarlab/_roman.js').write_text('window.ROMAN = ' + json.dumps(R, separators=(',', ':')) + ';\n')
    return len(rows), rows[-1][0]


def bake_l2():
    start = (NOW - dt.timedelta(days=7)).replace(minute=0, second=0, microsecond=0)
    stop = start + dt.timedelta(days=127)
    out = {'src': 'JPL Horizons, geocentric ecliptic vectors', 'built': NOW.strftime('%Y-%m-%d')}
    for key, cmd in (('jwst', '-170'), ('euclid', '-680')):
        rows = horizons(cmd, '500@399', start.strftime('%Y-%m-%d %H:%M'), stop.strftime('%Y-%m-%d %H:%M'), '6h')
        out[key] = {'t0': ms(rows[0][0]), 'step': 6 * 3600000, 'n': len(rows), 'p': [lon_km(r) for r in rows]}
    (ROOT / '_solarlab/_l2craft.js').write_text('window.L2CRAFT = ' + json.dumps(out, separators=(',', ':')) + ';\n')


def bake_parker():
    """Heliocentric distance (AU) and speed (km/s), 3-hourly, two days back to 150 ahead;
    perihelia are the local minima, refined to the hour."""
    AU = 149597870.7
    start = (NOW - dt.timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    rows = horizons('-96', '500@10', start.strftime('%Y-%m-%d %H:%M'),
                    (start + dt.timedelta(days=152)).strftime('%Y-%m-%d %H:%M'), '3h')
    ser = [[round(math.sqrt(r[1]**2 + r[2]**2 + r[3]**2) / AU, 5),
            round(math.sqrt(r[4]**2 + r[5]**2 + r[6]**2), 2)] for r in rows]
    peri = []
    for i in range(1, len(ser) - 1):
        if ser[i][0] < 0.2 and ser[i][0] <= ser[i - 1][0] and ser[i][0] < ser[i + 1][0]:
            c = rows[i][0]
            fine = horizons('-96', '500@10', (c - dt.timedelta(hours=4)).strftime('%Y-%m-%d %H:%M'),
                            (c + dt.timedelta(hours=4)).strftime('%Y-%m-%d %H:%M'), '10m')
            best = min(fine, key=lambda r: r[1]**2 + r[2]**2 + r[3]**2)
            peri.append({'t': ms(best[0]), 'au': round(math.sqrt(best[1]**2 + best[2]**2 + best[3]**2) / AU, 5),
                         'kms': round(math.sqrt(best[4]**2 + best[5]**2 + best[6]**2), 1)})
    return {'src': 'JPL Horizons, target -96, heliocentric', 't0': ms(rows[0][0]), 'step': 3 * 3600000,
            'n': len(ser), 's': ser, 'perihelia': peri}


# ── WEBB: STScI's published observing schedule ───────────────────────────────
SCHED_IDX = 'https://www.stsci.edu/jwst/science-execution/observing-schedules'


def bake_webb_schedule():
    idx = get(SCHED_IDX).decode('utf-8', 'replace')
    links = sorted(set(re.findall(r'href="([^"]*_documents/(\d{8})_report_\d{8}\.txt)"', idx)), key=lambda x: x[1])
    if not links: raise RuntimeError('no schedule links on the index page')
    href, week = links[-1]
    url = href if href.startswith('http') else 'https://www.stsci.edu' + href
    txt = get(url).decode('utf-8', 'replace').split('\n')
    hi = next(i for i, l in enumerate(txt) if l.startswith('VISIT ID'))
    dashes = txt[hi + 1]
    spans = [(m.start(), m.end()) for m in re.finditer(r'-+', dashes)]
    names = [txt[hi][a:b + 2].strip() for a, b in spans]
    rows = []
    for line in txt[hi + 2:]:
        if not line.strip(): continue
        f = {names[k]: line[a:(spans[k + 1][0] if k + 1 < len(spans) else len(line))].strip() for k, (a, b) in enumerate(spans)}
        vt, start = f.get('VISIT TYPE', ''), f.get('SCHEDULED START TIME', '')
        if not vt.startswith('PRIME') or not re.match(r'\d{4}-\d\d-\d\dT', start): continue
        d = re.match(r'(\d+)/(\d+):(\d+):(\d+)', f.get('DURATION', ''))
        dur = (int(d[1]) * 86400 + int(d[2]) * 3600 + int(d[3]) * 60 + int(d[4])) if d else 0
        t = dt.datetime.strptime(start, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
        rows.append({'t': ms(t), 'dur': dur, 'inst': f.get('SCIENCE INSTRUMENT AND MODE', ''),
                     'target': f.get('TARGET NAME', ''), 'cat': f.get('CATEGORY', ''),
                     'kw': f.get('KEYWORDS', ''), 'visit': f.get('VISIT ID', '')})
    if len(rows) < 5: raise RuntimeError('schedule parsed to %d rows' % len(rows))
    rows.sort(key=lambda r: r['t'])
    return {'src': url, 'page': SCHED_IDX, 'week': week, 'start': rows[0]['t'],
            'end': max(r['t'] + r['dur'] * 1000 for r in rows), 'rows': rows}


# ── NASA MAST: what Hubble and Webb observed lately ──────────────────────────
def mast(coll, days=2):
    now_mjd = time.time() / 86400 + 40587
    req = {'service': 'Mast.Caom.Filtered', 'format': 'json', 'pagesize': 3000, 'page': 1,
           'params': {'columns': 'instrument_name,target_name,t_min,t_exptime,obs_id,jpegURL,dataRights,'
                                 'target_classification,obs_title,proposal_id,filters',
                      'filters': [{'paramName': 'obs_collection', 'values': [coll]},
                                  {'paramName': 'intentType', 'values': ['science']},
                                  {'paramName': 't_min', 'values': [{'min': now_mjd - days, 'max': now_mjd + 1}]}]}}
    j = json.loads(get('https://mast.stsci.edu/api/v0/invoke',
                       data=urllib.parse.urlencode({'request': json.dumps(req)}).encode(), timeout=180))
    if j.get('status') != 'COMPLETE': raise RuntimeError('MAST %s: %s' % (coll, j.get('msg')))
    return j['data']


def mjd_ms(m): return int((m - 40587) * 86400000)


def bake_mast(coll):
    rows = mast(coll)
    newest = {}
    for r in rows:                                  # one line per target: its latest visit
        k = r['target_name']
        if k not in newest or r['t_min'] > newest[k]['t_min']: newest[k] = r
    items = sorted(newest.values(), key=lambda r: -r['t_min'])[:14]
    out = []
    for r in items:
        it = {'target': r['target_name'], 'inst': r['instrument_name'], 't': mjd_ms(r['t_min']),
              'title': (r['obs_title'] or '').strip(), 'cls': r['target_classification'] or '',
              'prop': r['proposal_id'], 'public': r['dataRights'] == 'PUBLIC'}
        out.append(it)
    return {'n_obs': len(rows), 'n_targets': len(newest), 'newest': mjd_ms(max(r['t_min'] for r in rows)) if rows else None,
            'items': out}


def main():
    prev = {}
    try: prev = json.loads((ROOT / 'observatories.json').read_text())
    except Exception: pass
    out = {'built': ms(NOW)}
    # each piece is independent: one source down keeps the last good copy of that piece
    for key, fn in (('webb', bake_webb_schedule), ('parker', bake_parker),
                    ('hubble_obs', lambda: bake_mast('HST')),
                    ('webb_obs', lambda: bake_mast('JWST'))):
        try:
            out[key] = fn(); print('ok', key)
        except Exception as e:
            print('FAILED', key, e)
            if key in prev: out[key] = prev[key]
    for label, fn in (('roman', bake_roman), ('l2', bake_l2)):
        try: print('ok', label, fn())
        except Exception as e: print('FAILED', label, e)
    (ROOT / 'observatories.json').write_text(json.dumps(out, separators=(',', ':')))
    print('wrote observatories.json', len(json.dumps(out)), 'bytes')


if __name__ == '__main__':
    main()
