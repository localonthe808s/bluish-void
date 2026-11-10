#!/usr/bin/env python3
"""NGWMN logs this machine could not fetch (2026-11-08: www.usgs.gov's firewall blocked the bake machine's IP after a 12-thread run).
Run from GitHub Actions (workflow ngwmn-logs.yml): reads ngwmn_missing.json ([[agency, site], ...]), fetches each well's LOG XML
politely (2 at a time, a pause before each request), writes <agency>_<site>.xml into OUTDIR (the same names as src_ngwmn's cache),
and stops cleanly on a 403/429 so a rerun picks up where it left off. The workflow uploads OUTDIR as an artifact; locally:
gh run download <id> -n ngwmn-logs -D <wells_cache>/ngwmn, then rerun wells_bake.py.
    python3 ngwmn_fetch_missing.py OUTDIR"""
import concurrent.futures as cf, json, os, re, sys, threading, time, urllib.error, urllib.request
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid.com wells bake)'}
LOG = 'https://www.usgs.gov/apps/ngwmn/ngwmn_cache/data/%s/%s/LOG'
STOP = threading.Event()


def one(a_s, out):
    a, s = a_s; path = os.path.join(out, '%s_%s.xml' % (a, re.sub(r'\W', '_', s)))
    if STOP.is_set() or os.path.exists(path): return 0
    time.sleep(0.6)
    for k in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(LOG % (a, s), headers=UA), timeout=90).read(); open(path, 'wb').write(b); return 1
        except urllib.error.HTTPError as e:
            if e.code in (403, 429): STOP.set(); print('blocked', e.code, 'stopping', flush=True); return 0
            if e.code == 404: return 0
            time.sleep(4 * (k + 1))
        except Exception: time.sleep(4 * (k + 1))
    return 0


if __name__ == '__main__':
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    todo = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ngwmn_missing.json')))
    n = 0
    with cf.ThreadPoolExecutor(2) as ex:
        for i, r in enumerate(ex.map(lambda x: one(x, out), todo)):
            n += r
            if i % 250 == 0: print(i, 'of', len(todo), 'fetched', n, flush=True)
    print('fetched', n, 'of', len(todo), 'blocked' if STOP.is_set() else 'done')
