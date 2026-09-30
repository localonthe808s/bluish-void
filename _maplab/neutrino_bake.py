"""NEUTRINO HUNTERS (2026-09-30): IceCube's public alerts, baked for the page.

IceCube publishes every astrophysical-neutrino alert within a minute through NASA's
GCN; the archive tables at gcn.gsfc.nasa.gov are the public record (no CORS, so the
page cannot read them itself). This keeps the newest of each event (a notice is
revised as the reconstruction improves) and writes neutrino/icecube.json:
  tracks   gold / bronze track alerts (a muon's straight track through the ice)
  cascades cascade alerts (a shower: a sphere of light, poorer direction)
Fields: id, date (ISO, UT), type, ra, dec (deg), err90 (arcmin), energy (TeV),
signalness (0..1, tracks only), far (false alarms a year). Hourly is plenty: a few
alerts a month.
"""
import datetime, html, json, os, re, sys, urllib.request

OUT = sys.argv[1] if len(sys.argv) > 1 else '_neutrino_out'
os.makedirs(OUT, exist_ok=True)
GCN = 'https://gcn.gsfc.nasa.gov/'
UA = {'User-Agent': 'bluishvoid.com neutrino bake (contact via site)'}


def rows(url):
    s = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode('utf-8', 'ignore')
    out = []
    for r in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
        cells = [html.unescape(re.sub(r'<[^>]+>', ' ', c)).split() for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)]
        cells = [' '.join(c) for c in cells]
        if cells and re.match(r'^\d+_\d+$', cells[0]):
            out.append(cells)
    return out


def when(d, t):
    # 26/09/30 + 00:44:43.39 -> 2026-09-30T00:44:43Z
    yy, mm, dd = d.split('/')
    return '20%s-%s-%sT%sZ' % (yy, mm, dd, t.split('.')[0])


def tracks():
    best = {}
    for c in rows(GCN + 'amon_icecube_gold_bronze_events.html'):
        try:
            rid, rev, d, t, typ, ra, dec, e90, e50, en, sig, far = c[:12]
            rec = {'id': rid, 'rev': int(rev), 'date': when(d, t), 'type': typ.upper(), 'ra': float(ra), 'dec': float(dec),
                   'err90': float(e90), 'err50': float(e50), 'energy': round(float(en), 1), 'signalness': round(float(sig), 3), 'far': round(float(far), 3)}
        except Exception:
            continue
        if rid not in best or rec['rev'] > best[rid]['rev']:
            best[rid] = rec
    return sorted(best.values(), key=lambda r: r['date'], reverse=True)


def cascades():
    best = {}
    for c in rows(GCN + 'amon_icecube_cascade_events.html'):
        try:
            rid, d, t, rev, stream, typ, ra, dec, e90, e50, en, far = c[:12]
            rec = {'id': rid, 'rev': int(rev), 'date': when(d, t), 'type': 'CASCADE', 'ra': float(ra), 'dec': float(dec),
                   'err90': float(e90) * 60, 'err50': float(e50) * 60, 'energy': round(float(en), 1), 'far': round(float(far), 3)}   # cascade errors are in degrees
        except Exception:
            continue
        if rid not in best or rec['rev'] > best[rid]['rev']:
            best[rid] = rec
    return sorted(best.values(), key=lambda r: r['date'], reverse=True)


def snews(prev):
    """SNEWS, the SuperNova Early Warning System (Super-K, IceCube, KM3NeT, HALO, LVD, KamLAND, Borexino in
    coincidence). There is no status feed: the network has never fired since it went automated in 2005, and its
    site says nothing live. What CAN be watched is the site itself -- its news page is fingerprinted every bake,
    and a change is reported with the date it was first seen (and its first line), so the widget stops claiming
    quiet and points at their page until the change is a week old."""
    import hashlib
    now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')
    out = {'checked': now, 'hash': None, 'changed_at': None, 'head': '', 'ok': False}
    old = ((prev or {}).get('snews') or {})
    try:
        s = urllib.request.urlopen(urllib.request.Request('https://www.phy.bnl.gov/snews/news.html', headers=UA), timeout=30).read().decode('utf-8', 'ignore')
        t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'<!--.*?-->', ' ', s, flags=re.S))).strip()
        body = t.rsplit('SNEWS News', 1)[-1].strip()
        out['hash'] = hashlib.sha1(body.encode()).hexdigest()[:12]
        out['head'] = body[:140]
        out['ok'] = True
        if old.get('hash') and old['hash'] != out['hash']:
            out['changed_at'] = now
        elif old.get('changed_at'):
            out['changed_at'] = old['changed_at']       # carried until the page settles a week
    except Exception as e:
        out['head'] = 'unreachable: %s' % e
        out['hash'] = old.get('hash'); out['changed_at'] = old.get('changed_at')
    return out


def previous():
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request('https://cdn.bluishvoid.com/neutrino/icecube.json?x=%d' % int(datetime.datetime.utcnow().timestamp()), headers=UA), timeout=30).read().decode())
    except Exception:
        return None


def main():
    tr, ca = tracks(), cascades()
    prev = previous()
    year = datetime.datetime.utcnow().year
    ytd = [r for r in tr if r['date'].startswith(str(year))]
    out = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'source': GCN + 'amon.html',
           'tracks': tr[:40], 'cascades': ca[:20],
           'counts': {'tracks_total': len(tr), 'cascades_total': len(ca), 'tracks_this_year': len(ytd),
                      'gold_this_year': sum(1 for r in ytd if r['type'] == 'GOLD')},
           'snews': snews(prev)}
    with open(os.path.join(OUT, 'icecube.json'), 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print('tracks', len(tr), 'cascades', len(ca), 'newest', tr[0] if tr else None)


if __name__ == '__main__':
    main()
