#!/usr/bin/env python3
"""MBARI DEEP-SEA SIGHTINGS (user 2026-11-09: "build the mbari sightings layer").

The public VARS annotation database behind MBARI's Deep-Sea Guide (calypso.mbari.org/anno/v1, the annosaurus API; snake_case
query fields): every annotation from MBARI's ROV dives since 2024-01-01 with its place, depth and water (temperature, oxygen,
salinity). The public set runs well behind the dives (11-09: the newest public annotation was from Oct 2024), so the layer
says "latest annotated dives", never "now". One point per animal per spot (0.01 degree) and 50 m of depth; the frame grab is
linked, not copied (MBARI material: non-commercial educational use, credit MBARI). Common names from the knowledge base (kb/v1).
Out: R2 ocean/mbari_sightings_v1.json     python3 mbari_sightings_bake.py OUT.json [--upload]
"""
import json, re, subprocess, sys, time, urllib.parse, urllib.request
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid.com MBARI sightings bake)', 'Content-Type': 'application/json'}
A = 'https://calypso.mbari.org/anno/v1/fast'
KB = 'https://calypso.mbari.org/kb/v1/concept/'
SKIP = re.compile(r'^(sinker|nil|marine snow|trash|equipment|physical-object|object|organism|Aves|unknown|detritus|feces|fecal pellet|bacterial mat|bubble|rock|sediment|mud|sand)$', re.I)


def post(body):
    for a in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(A, data=json.dumps(body).encode(), headers=UA), timeout=300))['content']
        except Exception as e: print('  retry', a, e, flush=True); time.sleep(10 * (a + 1))
    raise SystemExit('anno query failed')


GROUPS = [('Cephalopoda', 'squid'), ('Actinopterygii', 'fish'), ('Chondrichthyes', 'fish'), ('Myxini', 'fish'), ('Sarcopterygii', 'fish'), ('Ctenophora', 'comb'),
          ('Cnidaria', 'jelly'), ('Arthropoda', 'crust'), ('Echinodermata', 'star'), ('Tunicata', 'salp'), ('Annelida', 'worm'), ('Porifera', 'sponge'), ('Mollusca', 'mollusc'), ('Animalia', 'other')]


def lineage(name):
    """the knowledge base's path from the root to this concept: [(name, rank, [alternative names])]"""
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(KB.replace('/concept/', '/phylogeny/up/') + urllib.parse.quote(name), headers={'User-Agent': UA['User-Agent']}), timeout=60))
    except Exception: return []
    out = []
    while d:
        out.append((d.get('name'), d.get('rank'), d.get('alternativeNames') or [])); ch = d.get('children') or []; d = ch[0] if ch else None
    return out


def classify(name):
    L = lineage(name); names = [x[0] for x in L]
    grp = next((g for k, g in GROUPS if k in names), None)
    cn = None
    for nm, rk, alt in reversed(L):   # the most specific common name: the concept's own, else its nearest ancestor's
        low = [a for a in alt if a and a == a.lower() and '-' not in a and len(a) > 3]
        if low: cn = low[0] if nm == name else (low[0] if not cn else cn); break
    return grp, cn


def main(out, up):
    since = '2024-01-01T00:00:00Z'; until = time.strftime('%Y-%m-%dT00:00:00Z', time.gmtime(time.time() + 86400)); off = 0; rows = []
    while True:
        page = post({'min_timestamp': since, 'max_timestamp': until, 'limit': 5000, 'offset': off, 'data': True})
        rows += page; print('page', off // 5000, len(page), flush=True)
        if len(page) < 5000 or off >= 5000 * 60: break
        off += 5000; time.sleep(2)
    keep = {}
    for r in rows:
        if r.get('group') != 'ROV' or SKIP.match(r.get('concept') or ''): continue
        d = r.get('ancillary_data') or {}; la, lo, z = d.get('latitude'), d.get('longitude'), d.get('depth_meters')
        if la is None or lo is None or z is None or not (-90 < la < 90 and -180 <= lo <= 180) or (abs(la) < 0.01 and abs(lo) < 0.01): continue   # 0, 0 = no position
        k = (r['concept'], round(la, 2), round(lo, 2), int(z // 50))
        if k in keep: keep[k]['n'] += 1; continue
        img = next((i['url'] for i in r.get('image_references') or [] if (i.get('format') or '').endswith('jpeg')), None) or next((i['url'] for i in r.get('image_references') or []), None)
        keep[k] = {'c': r['concept'], 'la': round(la, 4), 'lo': round(lo, 4), 'z': round(z), 't': (r.get('recorded_timestamp') or '')[:10],
                   'tc': None if d.get('temperature_celsius') is None else round(d['temperature_celsius'], 1), 'o2': None if d.get('oxygen_ml_l') is None else round(d['oxygen_ml_l'], 2),
                   'im': img, 'n': 1}
    pts = list(keep.values()); names = {}
    for c in sorted({p['c'] for p in pts}):
        names[c] = classify(c); time.sleep(0.8)
    pts = [p for p in pts if names.get(p['c'], (None,))[0]]   # animals only (the knowledge base puts rocks, trash and gear outside Animalia)
    for p in pts:
        g, cn = names[p['c']]; p['g'] = g
        if cn: p['cn'] = cn
    for p in pts:
        for k in [k for k, v in p.items() if v is None]: del p[k]
    j = {'built': int(time.time()), 'newest': max((p['t'] for p in pts), default=None), 'oldest': min((p['t'] for p in pts), default=None), 'rows': len(rows), 'pts': pts}
    json.dump(j, open(out, 'w'), separators=(',', ':'))
    print('rows', len(rows), 'points', len(pts), 'concepts', len(names), 'newest', j['newest'])
    if up:
        import os
        if os.environ.get('R2_ACCOUNT_ID'):
            subprocess.run(['aws', 's3', 'cp', out, 's3://bluishvoid-bg/ocean/mbari_sightings_v1.json', '--content-type', 'application/json', '--cache-control', 'public, max-age=86400',
                            '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
        else:
            subprocess.run(['rclone', 'copyto', out, 'r2:bluishvoid-bg/ocean/mbari_sightings_v1.json', '--s3-no-check-bucket', '--header-upload', 'Content-Type: application/json',
                            '--header-upload', 'Cache-Control: public, max-age=86400'], check=True)


if __name__ == '__main__':
    main(sys.argv[1], '--upload' in sys.argv)
