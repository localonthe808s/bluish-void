#!/usr/bin/env python3
"""RADIO (user 2026-11-21: "make sure those are legal to use this way, build the map view, do a global view").

The global layer: every station in Radio Browser (radio-browser.info, a community-run open directory) that has a map position,
a working HTTPS stream (its last check passed). UK LISTENERS are the line, not UK stations: the file answers 451 in the UK. The page plays each station's OWN stream URL in an
<audio> element: the listener's browser connects straight to the station, nothing is relayed, recorded or re-hosted (the
directory model). Out: OUT/stations_v1.json {built, n, src, rows: [[lat, lon, name, url, homepage, cc, place, tags, codec,
bitrate, votes, 0, '', licensee, city of license]]} (the last two from the FCC, US call-sign stations only).
Run: python3 _radiobake/bake.py OUT
"""
import sys, os, re, json, math, socket, random, urllib.request, datetime

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


FCC = 'https://transition.fcc.gov/fcc-bin/%sq?list=4&size=9&status=LIC'


def fcc():
    """WHO HOLDS THE LICENSE (user 2026-11-21: "can you name the college"): the FCC's public FM and AM lists (US government data),
    call sign -> [(city of license, state, licensee, lat, lon)]"""
    out = {}
    for band in ('fm', 'am'):
        fn = os.path.join(os.environ.get('FCC_DIR', ''), band + '.txt')   # curl fetches them (the FCC answers Python's client 403)
        try:
            txt = open(fn, encoding='latin-1').read() if os.environ.get('FCC_DIR') else urllib.request.urlopen(urllib.request.Request(FCC % band, headers={'User-Agent': 'Mozilla/5.0'}), timeout=600).read().decode('latin-1')
        except Exception as e:
            print('fcc', band, 'unreachable', e)
            continue
        for ln in txt.splitlines():
            f = [x.strip() for x in ln.split('|')]
            if len(f) < 28 or f[12] != 'US' or not f[1]:
                continue
            try:
                la = (int(f[20]) + int(f[21]) / 60 + float(f[22]) / 3600) * (-1 if f[19] == 'S' else 1)
                lo = (int(f[24]) + int(f[25]) / 60 + float(f[26]) / 3600) * (-1 if f[23] == 'W' else 1)
            except ValueError:
                continue
            call = re.sub(r'-(FM|LP|AM|TV)$', '', f[1])
            out.setdefault(call, []).append((f[10], f[11], f[27], la, lo))
    print('fcc calls', len(out))
    return out


def km(a, b, c, d):
    p = math.pi / 180
    return 12742 * math.asin(math.sqrt(math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2))


# GENRES (user 2026-11-21: "do not all stations have a genre?" -> "yes do 1 and 2"): 1) the volunteers' free tags are mapped onto one
# vocabulary -- place names, frequencies and filler ("music", "hits", "am") dropped, spellings merged ("80's", "80er", "1980s" -> 80S;
# "hiphop" -> HIP-HOP) -- up to three; 2) a station left with none gets the genres its NAME states ("Jazz FM", "Classic Rock 101"),
# and a school-held FCC license makes it COLLEGE RADIO. A station whose name names nothing keeps none (the card says LIVE RADIO).
G = [
    ('CLASSIC ROCK', r'classic rock'), ('ALTERNATIVE', r'alternative|alt rock'), ('INDIE', r'\bindie'), ('METAL', r'metal'), ('PUNK', r'\bpunk'),
    ('SMOOTH JAZZ', r'smooth jazz'), ('JAZZ', r'\bjazz'), ('BLUES', r'\bblues'), ('SOUL', r'\bsoul\b'), ('R&B', r'\br ?& ?b\b|\brnb\b|rhythm and blues'),
    ('FUNK', r'\bfunk\b'), ('DISCO', r'\bdisco\b'), ('HIP-HOP', r'hip[- ]?hop'), ('RAP', r'\brap\b'), ('REGGAETON', r'reggaeton'), ('REGGAE', r'\breggae\b'),
    ('DANCEHALL', r'dancehall'), ('DEEP HOUSE', r'deep house'), ('HOUSE', r'\bhouse\b'), ('TECHNO', r'\btechno'), ('TRANCE', r'\btrance\b'),
    ('DRUM AND BASS', r'drum ?(and|&|n) ?bass|\bdnb\b'), ('DUBSTEP', r'dubstep'), ('DUB', r'^dub$'), ('AMBIENT', r'\bambient'), ('CHILLOUT', r'chill'),
    ('LOUNGE', r'lounge'), ('DOWNTEMPO', r'downtempo'), ('EXPERIMENTAL', r'experimental|avant'), ('ELECTRONIC', r'electronic|electronica|\belectro\b|\bedm\b'),
    ('DANCE', r'\bdance\b|eurodance'), ('CLASSICAL', r'classical|klassik|cl[aá]sica\b|\bopera\b|baroque|symphon|classic fm|classic radio'), ('CLASSIC COUNTRY', r'classic country'),
    ('BLUEGRASS', r'bluegrass'), ('COUNTRY', r'\bcountry\b'), ('AMERICANA', r'americana'), ('FOLK', r'\bfolk'), ('WORLD', r'world music|\bworld\b'),
    ('AFROBEATS', r'afrobeat'), ('SALSA', r'\bsalsa\b'), ('CUMBIA', r'cumbia'), ('BACHATA', r'bachata'), ('MERENGUE', r'merengue'), ('BANDA', r'^banda$'),
    ('REGIONAL MEXICAN', r'regional mexican|grupera|norte[ñn]a'), ('SERTANEJO', r'sertanej'), ('MPB', r'^mpb$'), ('SAMBA', r'\bsamba\b'), ('SCHLAGER', r'schlager'),
    ('BOLLYWOOD', r'bollywood'), ('LATIN', r'\blatin|latino'), ('GOSPEL', r'gospel'), ('CATHOLIC', r'catholic|cat[oó]lic'),
    ('CHRISTIAN', r'christian|cristian|worship|praise|\bhymns?\b'), ('ISLAMIC', r'islam|quran'), ('OLDIES', r'oldies|golden'),
    ('TOP 40', r'top ?40|top hits|\bcharts?\b|contemporary hits'), ('ADULT CONTEMPORARY', r'adult contemporary|\bac\b'), ('EASY LISTENING', r'easy listening|soft hits'),
    ('BIG BAND', r'big band|swing'), ('SOUNDTRACKS', r'soundtrack|film score'), ('INSTRUMENTAL', r'instrumental'), ('KIDS', r'\bkids\b|children'),
    ('CHRISTMAS', r'christmas|navidad'), ('COMEDY', r'comedy'), ('OLD TIME RADIO', r'old time radio|\botr\b'), ('NEWS', r'\bnews\b|noticias|nachrichten|informa'),
    ('TALK', r'\btalk\b|spoken'), ('SPORTS', r'sport|deportes|futebol|f[uú]tbol'), ('PUBLIC RADIO', r'\bnpr\b|public radio'),
    ('COMMUNITY RADIO', r'community'), ('COLLEGE RADIO', r'college|campus|student radio|university radio'), ('ECLECTIC', r'eclectic|ecl[eé]tica|variety|various|freeform'),
    ('ROCK', r'\brock\b'), ('POP', r'\bpop\b'), ('BALLADS', r'balada|ballad'), ('CLASSIC HITS', r'^classic hits$|^adult hits$'),
]
G = [(n, re.compile(p, re.I)) for n, p in G]
DEC = re.compile(r"^(?:19)?([5-9]0)(?:'?s|er)$|^(?:20)?(00|10|20)(?:'?s|er)$", re.I)


def genres(tags):
    out = []
    for t in [x.strip() for x in tags.split(',') if x.strip()]:
        m = DEC.match(t.replace(' ', ''))
        hit = (m.group(1) + 'S') if m and m.group(1) else ('20' + m.group(2) + 'S') if m else None
        if not hit:
            hit = next((n for n, rx in G if rx.search(t)), None)
        if hit and hit not in out:
            out.append(hit)
    return out[:3]


def name_genres(nm):
    nm = re.sub(r'little rock|rockford|rockland|rockville|rock hill|round rock|rocky', ' ', nm, flags=re.I)
    out = []
    for n, rx in G:
        if n in ('HITS', 'DUB', 'BANDA', 'MPB', 'WORLD', 'ADULT CONTEMPORARY', 'COMMUNITY RADIO', 'KIDS', 'GOSPEL') and n != 'GOSPEL':
            continue
        if rx.search(nm) and n not in out:
            out.append(n)
    m = re.search(r"\b(?:19)?([5-9]0)'?s\b", nm)
    if m and len(out) < 3:
        out.append(m.group(1) + 'S')
    return out[:2]


CALL = re.compile(r'\b([KW][A-Z]{2,3})(?:-?(?:FM|AM|LP|LPFM|HD\d?))?\b')


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
                     (s.get('codec') or '').upper()[:6], int(s.get('bitrate') or 0), int(s.get('votes') or 0), 0, '', '', ''])
    # US stations whose name carries a call sign: the licensee and city of license, if the FCC's transmitter is within 150 km
    F, nf = fcc(), 0
    for r in rows:
        if r[5] != 'US':
            continue
        best = None
        for m in CALL.finditer(r[2].upper()):
            for c in F.get(m.group(1), []):
                d = km(r[0], r[1], c[3], c[4])
                if d <= 150 and (best is None or d < best[0]):
                    best = (d, c)
        if best:
            c = best[1]; r[13] = ' '.join(c[2].split())[:80]; r[14] = (c[0].title() + ', ' + c[1])[:50]; nf += 1
    print('fcc matched', nf)
    SCH = re.compile(r'COLLEGE|UNIVERSITY|INSTITUTE OF|SCHOOL|ACADEMY|SEMINARY|REGENTS')
    nn = nc = 0
    for r in rows:
        g = genres(r[7])
        if not g:
            g = name_genres(r[2]); nn += bool(g)
        if SCH.search(r[13] or '') and 'COLLEGE RADIO' not in g:
            g = (g + ['COLLEGE RADIO'])[:3]
        nc += not g
        r[7] = ','.join(g)
    print('genres: from names', nn, '| still none', nc)
    meta = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'n': len(rows), 'src': host, 'rows': rows}
    json.dump(meta, open(os.path.join(out, 'stations_v1.json'), 'w'), separators=(',', ':'), ensure_ascii=False)
    print('stations', len(S), '-> kept', len(rows), 'from', host, os.path.getsize(os.path.join(out, 'stations_v1.json')) // 1024, 'KB')


if __name__ == '__main__':
    main()
