#!/usr/bin/env python3
"""RADIO (user 2026-11-21: "make sure those are legal to use this way, build the map view, do a global view").

The global layer: every station in Radio Browser (radio-browser.info, a community-run open directory) that has a map position,
a working HTTPS stream (its last check passed). UK LISTENERS are the line, not UK stations: the file answers 451 in the UK. The page plays each station's OWN stream URL in an
<audio> element: the listener's browser connects straight to the station, nothing is relayed, recorded or re-hosted (the
directory model). Out: OUT/stations_v1.json {built, n, src, rows: [[lat, lon, name, url, homepage, cc, place, tags, codec,
bitrate, votes]]}.
Run: python3 _radiobake/bake.py OUT
"""
import sys, os, json, socket, random, urllib.request, datetime

UA = {'User-Agent': 'BluishVoid/1.0'}
FALLBACK = ['de1.api.radio-browser.info', 'de2.api.radio-browser.info', 'fi1.api.radio-browser.info', 'nl1.api.radio-browser.info']


def servers():
    """Radio Browser asks clients to pick a server from the all.api.radio-browser.info DNS round robin"""
    hs = []
    try:
        for ip in {a[4][0] for a in socket.getaddrinfo('all.api.radio-browser.info', 443, proto=socket.IPPROTO_TCP)}:
            try:
                hs.append(socket.gethostbyaddr(ip)[0])
            except Exception:
                pass
    except Exception:
        pass
    hs = [h for h in hs if h.endswith('radio-browser.info')] or FALLBACK
    random.shuffle(hs)
    return hs


def get(path):
    err = None
    for h in servers():
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request('https://' + h + path, headers=UA), timeout=180)), h
        except Exception as e:
            err = e
    raise SystemExit('radio-browser unreachable: %s' % err)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'out'
    os.makedirs(out, exist_ok=True)
    S, host = get('/json/stations/search?has_geo_info=true&is_https=true&hidebroken=true&limit=200000&order=votes&reverse=true')
    rows, seen = [], set()
    for s in S:
        u = (s.get('url_resolved') or '').strip()
        try:
            la, lo = float(s.get('geo_lat')), float(s.get('geo_long'))
        except (TypeError, ValueError):
            continue
        if not u.startswith('https://') or s.get('lastcheckok') != 1 or not (-90 < la < 90 and -180 <= lo <= 180) or (la == 0 and lo == 0):
            continue
        if s.get('hls') == 1:
            continue                                                # HLS needs a JS player, not <audio> everywhere
        if u in seen:
            continue
        seen.add(u)
        nm = ' '.join((s.get('name') or '').split())[:80]
        if not nm:
            continue
        tags = ','.join([t.strip() for t in (s.get('tags') or '').split(',') if t.strip()][:3])[:60]
        place = (s.get('state') or '').strip()[:40]
        hp = (s.get('homepage') or '').strip()
        hp = hp if hp.startswith('http') else ''
        rows.append([round(la, 3), round(lo, 3), nm, u, hp[:200], (s.get('countrycode') or '').upper(), place, tags,
                     (s.get('codec') or '').upper()[:6], int(s.get('bitrate') or 0), int(s.get('votes') or 0)])
    meta = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'n': len(rows), 'src': host, 'rows': rows}
    json.dump(meta, open(os.path.join(out, 'stations_v1.json'), 'w'), separators=(',', ':'), ensure_ascii=False)
    print('stations', len(S), '-> kept', len(rows), 'from', host, os.path.getsize(os.path.join(out, 'stations_v1.json')) // 1024, 'KB')


if __name__ == '__main__':
    main()
