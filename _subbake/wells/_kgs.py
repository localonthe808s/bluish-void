"""Shared helpers for the KGS (Kansas Geological Survey) adapters: cached GET from the Ora_Archive, tolerant line decoding."""
import csv, os, time, urllib.request, zipfile

UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
BASE = 'https://www.kgs.ku.edu/PRS/Ora_Archive/'


def cache_dir(code):
    d = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), code)
    os.makedirs(d, exist_ok=True)
    return d


def fetch(code, name):
    p = os.path.join(cache_dir(code), name)
    if os.path.exists(p) and os.path.getsize(p) > 0: return p
    for a in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(BASE + name, headers=UA), timeout=600).read()
            open(p + '.part', 'wb').write(b); os.replace(p + '.part', p); return p
        except Exception:
            if a == 2: raise
            time.sleep(5 * (a + 1))


def _lines(fh):
    for b in fh:
        try: yield b.decode('utf-8')
        except UnicodeDecodeError: yield b.decode('latin-1')


def rows(code, zipname):
    """DictReader over the single text member of an Ora_Archive zip (decoded utf-8, else latin-1, line by line)."""
    z = zipfile.ZipFile(fetch(code, zipname))
    member = [n for n in z.namelist() if not n.endswith('/')][0]
    with z.open(member) as fh:
        for r in csv.DictReader(_lines(fh)):
            yield r


def num(s):
    try:
        v = float(str(s).strip().replace(',', ''))
        return v if v == v else None
    except Exception:
        return None


def inks(lat, lon):
    return lat is not None and lon is not None and 36.8 <= lat <= 40.2 and -102.2 <= lon <= -94.4
