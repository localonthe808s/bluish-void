#!/usr/bin/env python3
"""LOCAL STORM REPORTS (2026-11-16, user: "did we see that there were water spouts in SF today?" -> no -> "build the storm reports
layer go for it"). The NWS offices' Local Storm Reports -- waterspouts, funnel clouds, tornadoes, wind damage, hail, flooding,
slides, snow -- as the Iowa Environmental Mesonet serves them (keyless GeoJSON), baked so SEVERE's STORM REPORTS has a 3- and
7-day window without asking the IEM for a week of the country on every tap, and so the site keeps a memory of days like the
Bay's two waterspouts of 2026-11-16 (the SPC tornado list never carries a spout that stays over water).

    lsr/recent.json        {"at": unix, "since": iso, "n": rows, "days": {"YYYY-MM-DD" (UTC): [row, ...]}}   the last 8 days, every 6 h
    lsr/days/<date>.json   one finished UTC day, the same rows, rewritten while it is inside the 8-day pull (late filings land)
    row = [t (unix), lat, lon, type code, type text, magnitude|null, unit, city, state, wfo, remark (<= 300 chars), source]

    python3 _lsrbake/bake.py [--dry]
"""
import json, os, subprocess, sys, tempfile, time, urllib.request
from datetime import datetime, timedelta, timezone

BUCKET = 'bluishvoid-bg'
IEM = 'https://mesonet.agron.iastate.edu/geojson/lsr.php?sts=%s&ets=%s'
DAYS = 8


def fetch(sts, ets, tries=4):
    url = IEM % (sts, ets)
    for k in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bluishvoid.com storm reports bake'}), timeout=120).read()
            return json.loads(b.decode('utf-8', 'replace'))
        except Exception as e:
            print('retry', k, e); time.sleep(20 * (k + 1))
    raise SystemExit('the IEM did not answer')


def upload(path, key, cache):
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', path, 's3://%s/%s' % (BUCKET, key), '--content-type', 'application/json', '--cache-control', cache,
                        '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
    else:
        subprocess.run(['rclone', 'copyto', path, 'r2:%s/%s' % (BUCKET, key), '--s3-no-check-bucket',
                        '--header-upload', 'Content-Type: application/json', '--header-upload', 'Cache-Control: ' + cache], check=True)
    print('uploaded', key)


def main():
    now = datetime.now(timezone.utc)
    sts = (now - timedelta(days=DAYS)).strftime('%Y-%m-%dT%H:%MZ')
    ets = (now + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%MZ')
    j = fetch(sts, ets)
    days, seen, n = {}, set(), 0
    for f in j.get('features') or []:
        p = f.get('properties') or {}
        c = (f.get('geometry') or {}).get('coordinates') or []
        try:
            t = int(datetime.strptime(p['valid'][:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc).timestamp())
            lat, lon = round(float(c[1]), 3), round(float(c[0]), 3)
        except Exception:
            continue
        mag = p.get('magnitude')
        try:
            mag = None if mag in (None, '') else float(mag)
        except (TypeError, ValueError):
            mag = None
        row = [t, lat, lon, p.get('type') or '', p.get('typetext') or '', mag, p.get('unit') or '', p.get('city') or '',
               p.get('st') or p.get('state') or '', p.get('wfo') or '', (p.get('remark') or '')[:300], p.get('source') or '']
        k = (row[9], t, row[4], lat, lon)
        if k in seen:
            continue
        seen.add(k); n += 1
        days.setdefault(datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m-%d'), []).append(row)
    for d in days:
        days[d].sort(key=lambda r: r[0])
    doc = {'at': int(time.time()), 'since': sts, 'n': n, 'days': days}
    tmp = tempfile.gettempdir()
    path = os.path.join(tmp, 'lsr_recent.json'); json.dump(doc, open(path, 'w'), separators=(',', ':'))
    kinds = {}
    for rows in days.values():
        for r in rows:
            kinds[r[4]] = kinds.get(r[4], 0) + 1
    print('reports', n, 'days', len(days), 'bytes', os.path.getsize(path), 'top', sorted(kinds.items(), key=lambda x: -x[1])[:8])
    if n < 20:
        raise SystemExit('too few reports; keeping the published files')
    if '--dry' in sys.argv:
        return
    upload(path, 'lsr/recent.json', 'public, max-age=1800')
    today = now.strftime('%Y-%m-%d')
    for d, rows in sorted(days.items()):
        if d >= today:
            continue                                   # a day still filling stays in recent.json only
        dp = os.path.join(tmp, 'lsr_%s.json' % d); json.dump({'date': d, 'n': len(rows), 'rows': rows}, open(dp, 'w'), separators=(',', ':'))
        upload(dp, 'lsr/days/%s.json' % d, 'public, max-age=86400')


if __name__ == '__main__':
    main()
