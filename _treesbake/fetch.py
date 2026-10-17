"""Download the McCoy et al. 2022 city-tree CSVs (Zenodo 6726506, CC0) into a directory, skipping New York.

  python3 -I _treesbake/fetch.py <outdir>
"""
import json, os, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
rec = json.load(urllib.request.urlopen('https://zenodo.org/api/records/6726506'))
files = [f for f in rec['files'] if not f['key'].startswith('NewYork')]


def get(f):
    p = os.path.join(out, f['key'])
    if os.path.exists(p) and os.path.getsize(p) == f['size']:
        return f['key'], 'cached'
    err = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(f['links']['self'], timeout=300) as r, open(p + '.part', 'wb') as w:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    w.write(b)
            os.replace(p + '.part', p)
            if os.path.getsize(p) == f['size']:
                return f['key'], os.path.getsize(p)
            err = 'size mismatch'
        except Exception as e:
            err = e
    return f['key'], 'FAILED %s' % err


with ThreadPoolExecutor(6) as ex:
    for k, s in ex.map(get, files):
        print(k, s, flush=True)
