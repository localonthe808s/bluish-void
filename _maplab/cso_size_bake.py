#!/usr/bin/env python3
"""Join NYC DEP outfall DIMENSIONS onto the CITY map's CSO pipes.

WHY A SECOND SOURCE AT ALL.  The layer we render is baked from NYS DEC
("Combined Sewer Overflows (CSOs): Beginning 2013", data.ny.gov/resource/
ephi-ffu6.json).  That feed has no physical fields whatsoever -- its columns
are id, location, facility, waterbody, activation type and overflow counts.
It cannot tell you how big a pipe is.

NYC DEP's "Citywide Outfalls" (data.cityofnewyork.us/resource/8rjn-kpsh.json,
keyless, 5,428 rows of every outfall type) carries `of_size`, populated for
413 of its 415 CSO rows.  Two formats, both of which must be parsed:

    7' X 4'        box culvert, width x height
    48" DIA        round pipe, diameter   <- the DIA suffix is NOT optional in
                                             the regex; miss it and you match
                                             one row out of 198

THE JOIN IS CONFIRMED TWO WAYS, which is the only reason to trust it.  Match
on position and the outfall NUMBER agrees independently for 337 of 347 pairs
inside 30 ft -- the two agencies share the numbering.  So a pair is accepted
when the ids agree, or when it is spatially unambiguous and nothing conflicts.
Anything else is left unsized rather than guessed at.

WHAT THIS DOES NOT TELL YOU: where the pipe ENDS.  Both agencies record the
bulkhead -- measured against NYC's photogrammetric shoreline, DEP's median
outfall sits 2.0 ft from the surveyed wall and DEC's 4.2 ft.  A size is a
cross-section, not a reach.  Do not let a bigger glyph imply a pipe that
extends further into the water; that is not in any of this data.  (6-inch
orthoimagery at orthos.its.ny.gov answers it by eye for most pipes.)

Usage:  python3 _maplab/cso_size_bake.py [--write]
        Without --write it reports the match and changes nothing.
"""
import json, math, re, sys, urllib.request, collections, os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSO_JSON = os.path.join(REPO, 'city_cso.json')
DEP_URL = 'https://data.cityofnewyork.us/resource/8rjn-kpsh.json?$limit=6000'
DEC_URL = 'https://data.ny.gov/resource/ephi-ffu6.json?$limit=5000'
NYC_COUNTIES = ('Kings', 'Queens', 'New York', 'Bronx', 'Richmond')


def get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read().decode())


def feet(lat1, lon1, lat2, lon2):
    m = 111320.0
    dy = (lat2 - lat1) * m
    dx = (lon2 - lon1) * m * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy) * 3.28084


def norm_id(s):
    """'003A' / '3' / 'NCB-088' -> a comparable ('3','A') pair."""
    s = str(s or '').strip().upper()
    m = re.search(r'(\d+)\s*([A-Z]?)\s*$', s)
    if not m:
        return None
    return (str(int(m.group(1))), m.group(2))


def _inches(whole, frac):
    """9 5-3/4"  ->  5.75 inches.  DEP writes fractions this way."""
    v = float(whole or 0)
    if frac:
        m = re.match(r'(?:(\d+)-)?(\d+)/(\d+)', frac)
        if m:
            v = float(m.group(1) or v)
            v += float(m.group(2)) / float(m.group(3))
    return v


def parse_size(s):
    """-> dict(w, h, n, shape, label) ; None if unparseable.

    DEP's `of_size` is a sewer cross-section, and it carries more than numbers:

        48" DIA              round
        7' X 4'              box (rectangular)
        5' X 4' FT           FLAT-TOP section, not a unit suffix
        3' 6" X 2' 4" Egg    EGG-SHAPED brick sewer, the old ones
        DBL 15' X 9' 2"      TWO barrels side by side
        3BL 7' 4" X 7' 4"    three barrels;  4BL exists too
        DBL 144" DIA         two round barrels
        7' 8" X 7' 7" ARCH   arch section
        12' X 9' 5-3/4"      fractional inches

    One row reads `72BL 7'6" X 2'5"`, which would be seventy-two barrels and is
    almost certainly a typo in DEP's table.  It is parsed as written rather than
    corrected -- but `n` is deliberately NOT used to scale the drawn glyph for
    exactly this reason; it belongs in the popup text, where a reader can judge
    it.  Scale on `w` alone.

    The barrel count is not decoration -- a DBL 15 x 9'2" is two of those, and
    reading it as one understates the outfall by half.  `n` is that multiplier.
    """
    if not s:
        return None
    t = re.sub(r'\s+', ' ', str(s).strip().upper())
    n = 1
    m = re.match(r'^(DBL|DB|(\d+)BL)\s+(.*)$', t)
    if m:
        n = 2 if m.group(1) in ('DBL', 'DB') else int(m.group(2))
        t = m.group(3)
    shape = 'box'
    m = re.match(r'^(.*?)\s*(FT|EGG|ARCH)\s*$', t)
    if m:
        t = m.group(1)
        shape = {'FT': 'flat-top', 'EGG': 'egg', 'ARCH': 'arch'}[m.group(2)]
    FI = r"(\d+(?:\.\d+)?)\s*'?\s*(?:((?:\d+-)?\d+(?:/\d+)?)\s*\")?"
    m = re.match(r'^\s*' + FI + r'\s*X\s*' + FI + r'\s*$', t)
    if m:
        w = float(m.group(1)) + _inches(0, m.group(2)) / 12.0
        h = float(m.group(3)) + _inches(0, m.group(4)) / 12.0
        return dict(w=w, h=h, n=n, shape=shape, label=re.sub(r'\s+', ' ', str(s).strip()))
    m = re.match(r'^\s*(\d+(?:\.\d+)?)\s*"?\s*(?:DIA\.?)?\s*$', t)
    if m:
        d = float(m.group(1)) / 12.0
        return dict(w=d, h=None, n=n, shape='round',
                    label=re.sub(r'\s+', ' ', str(s).strip()))
    return None


def main():
    write = '--write' in sys.argv
    cso = json.load(open(CSO_JSON))
    pipes, wb, fac = cso['p'], cso['wb'], cso['fac']
    print(f'  our layer: {len(pipes)} pipes')

    dep_all = [r for r in get(DEP_URL) if r.get('latitude')]
    dep = [r for r in dep_all if r.get('outfall_ty') == 'CSO']
    print(f'  DEP rows: {len(dep_all)} of every type, {len(dep)} CSO '
          f'({sum(1 for r in dep if r.get("of_size"))} with a size)')

    # DEC raw, only to recover each pipe's outfall number for the id check --
    # our baked rows carry outfallId already, but the raw feed is what the
    # id agreement was measured against.
    dec = [r for r in get(DEC_URL)
           if r.get('county') in NYC_COUNTIES and r.get('latitude')]
    dec_at = {}
    for r in dec:
        dec_at[(round(float(r['latitude']), 5), round(float(r['longtitude']), 5))] = r

    sizes, widths, idx_of = [], [], {}
    stats = collections.Counter()
    unmatched = []

    for p in pipes:
        lon, lat, oid = p[0], p[1], p[3]
        # nearest DEP pipe, and whether the ids agree
        best, bd = None, 1e9
        for s in dep:
            d = feet(lat, lon, float(s['latitude']), float(s['longitude']))
            if d < bd:
                bd, best = d, s
        ok = False
        if best is not None:
            a, b = norm_id(oid), norm_id(best.get('unitid'))
            ids_agree = (a is not None and a == b)
            # Three ways in, in order of how much they prove:
            #   ids agree            -- the strong case, survives coordinate drift
            #   under 10 ft          -- overwhelming on its own. Rockaway and
            #                           26th Ward genuinely number their outfalls
            #                           differently between the two agencies
            #                           (DEC "3" vs DEP "ROC-001A", 0.1 ft apart),
            #                           so an id clash must not veto a pipe the
            #                           two surveys put in the same spot.
            #   under 30 ft, no clash
            if ids_agree and bd <= 400:
                ok = True; stats['by id + position'] += 1
            elif bd <= 10:
                ok = True; stats['by position (<10 ft)'] += 1
            elif bd <= 30 and not (a and b and a != b):
                ok = True; stats['by position (<30 ft)'] += 1
            elif a and b and a != b:
                stats['rejected: id clash, far'] += 1
            else:
                stats['rejected: no DEP pipe near'] += 1
        if ok and best.get('of_size'):
            parsed = parse_size(best['of_size'])
            if parsed:
                lab = parsed['label']
                if lab not in idx_of:
                    idx_of[lab] = len(sizes); sizes.append(lab); widths.append(round(parsed['w'], 2))
                if len(p) >= 8: p[7] = idx_of[lab]
                else: p.append(idx_of[lab])
                stats['sized'] += 1
                continue
            stats['size unparseable'] += 1
            print(f'    ! unparseable size {best["of_size"]!r} (outfall {oid})')
        # SECOND PASS, and it is deliberately separated from the first.
        #
        # A dozen pipes DEC calls a CSO have a DEP row one to six feet away
        # typed MS4, ABND, DIRECT or CLVT -- the two agencies disagree about
        # what the pipe IS, not about where it is or how big it is. At that
        # distance it is the same structure, and a cross-section is a physical
        # measurement either way, so the size is taken. What is NOT taken is
        # DEP's opinion of the classification: this does not reclassify our
        # layer, and the disagreement is reported below because it says some
        # of the 435 may not be live combined-sewer outfalls at all.
        alt, ad = None, 1e9
        for s in dep_all:
            if s.get('outfall_ty') == 'CSO':
                continue
            d = feet(lat, lon, float(s['latitude']), float(s['longitude']))
            if d < ad:
                ad, alt = d, s
        if alt is not None and ad <= 10 and alt.get('of_size'):
            parsed = parse_size(alt['of_size'])
            if parsed:
                lab = parsed['label']
                if lab not in idx_of:
                    idx_of[lab] = len(sizes); sizes.append(lab); widths.append(round(parsed['w'], 2))
                if len(p) >= 8: p[7] = idx_of[lab]
                else: p.append(idx_of[lab])
                stats['sized'] += 1
                stats[f'  ...from a DEP {alt.get("outfall_ty")} row'] += 1
                continue

        if len(p) >= 8: p[7] = -1
        else: p.append(-1)
        if not ok:
            unmatched.append((oid, wb[p[4]] if p[4] < len(wb) else '?', round(bd)))

    print()
    for k, v in stats.most_common():
        print(f'    {k:<24} {v:>4}')
    print(f'\n  SIZED: {stats["sized"]} / {len(pipes)} '
          f'({100*stats["sized"]/len(pipes):.0f}%)   distinct size labels: {len(sizes)}')
    if unmatched:
        print(f'  left unsized (first 8 of {len(unmatched)}):')
        for oid, w, d in unmatched[:8]:
            print(f'    outfall {oid:<6} {w[:26]:<26} nearest DEP pipe {d} ft')

    if write:
        cso['sz'] = sizes
        # WIDTH IN FEET PER LABEL, so the renderer never has to parse the
        # string. The glyph scales on this and ONLY this -- not on the barrel
        # count (one row claims 72 barrels and is surely a typo), and not on
        # height, because the mouth width is what a plan view can honestly show.
        cso['szw'] = widths
        json.dump(cso, open(CSO_JSON, 'w'), separators=(',', ':'))
        print(f'\n  wrote {CSO_JSON} ({os.path.getsize(CSO_JSON):,} bytes)')
    else:
        print('\n  (dry run -- pass --write to update city_cso.json)')


if __name__ == '__main__':
    main()
