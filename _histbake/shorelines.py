#!/usr/bin/env python3
"""NYC'S SHORELINES, SURVEYED (user 2026-10-28: "are there other historical maps we can use to show nyc water history?" -> HISTORICAL
WATERS). NOAA's Coast Survey topographic sheets (T-sheets), digitized line by line by NOAA's Shoreline Data Rescue projects and served
by the NOAA Shoreline Data Explorer (nsde.ngs.noaa.gov/downloads/<project>.zip, public domain): each line dated and classed.

Kept: the shore (mean high water, man-made shore, bulkheads, approximate shore) and the marsh edge, inside the city's box; piers are
dropped (they are what the shore grew, not the shore). Grouped into the surveys' three eras over NYC: 1873-1887, 1903-1914, 1928-1949.
Simplified to ~3 m, 5 decimals.

    python3 shorelines.py UNZIPPED_DIR OUT.json
"""
import glob, json, os, sys
import shapefile
from shapely.geometry import LineString, box

BOX = box(-74.27, 40.48, -73.68, 40.93)
SHORE = ('Natural.Mean High Water', 'Man-made', 'Man-made.Bulkhead Or Sea Wall', 'Undetermined.Approximate', 'Undetermined Alongshore Feature', 'Shoreline/Alongshore Feature Boundary')
MARSH = ('Natural.Apparent.Marsh Or Swamp',)


KX = 111320 * 0.7576; KY = 110540            # metres per degree at 40.75 N


def depier(c, back=30, out=20, maxrun=600):
    """THE SHORE, NOT ITS PIERS (user 2026-10-28: "improve these shoreline lines"): the surveyors drew every pier's outline as man-made
    shore, so a waterfront reads as teeth. Wherever the line leaves a point and comes back within `back` m of it, having gone more than
    `out` m away and run less than `maxrun` m, that finger is cut and the line closed across its base"""
    P = [(x * KX, y * KY) for x, y in c]; keep = []; i = 0; n = len(P)
    while i < n:
        keep.append(c[i]); run = 0; cut = None
        for j in range(i + 2, n):
            run += ((P[j][0] - P[j - 1][0]) ** 2 + (P[j][1] - P[j - 1][1]) ** 2) ** .5
            if run > maxrun: break
            if ((P[j][0] - P[i][0]) ** 2 + (P[j][1] - P[i][1]) ** 2) ** .5 < back:
                far = max(((P[k][0] - P[i][0]) ** 2 + (P[k][1] - P[i][1]) ** 2) ** .5 for k in range(i + 1, j))
                if far > out: cut = j
        i = cut if cut else i + 1
    return keep


def ispier(c):
    """a pier drawn on its own: a short line whose two ends sit close together on the bulkhead while its middle reaches out"""
    P = [(x * KX, y * KY) for x, y in c]
    L = sum(((P[i][0] - P[i - 1][0]) ** 2 + (P[i][1] - P[i - 1][1]) ** 2) ** .5 for i in range(1, len(P)))
    ends = ((P[0][0] - P[-1][0]) ** 2 + (P[0][1] - P[-1][1]) ** 2) ** .5
    reach = max(((q[0] - P[0][0]) ** 2 + (q[1] - P[0][1]) ** 2) ** .5 for q in P)
    return L < 1200 and ends < 110 and reach > 30 and L > 2.2 * ends


def chaikin(c, rounds=2):
    for _ in range(rounds):
        if len(c) < 3: return c
        o = [c[0]]
        for a, b in zip(c[:-1], c[1:]): o += [[a[0] * .75 + b[0] * .25, a[1] * .75 + b[1] * .25], [a[0] * .25 + b[0] * .75, a[1] * .25 + b[1] * .75]]
        o.append(c[-1]); c = o
    return c


def era(y):
    return 1880 if y < 1895 else 1910 if y < 1920 else 1935


def main(src, out):
    rows = []; n = {}; npier = [0]
    for shp in sorted(glob.glob(os.path.join(src, '*', 'historicl1.shp'))):
        r = shapefile.Reader(shp); f = [x[0] for x in r.fields[1:]]
        for sr in r.iterShapeRecords():
            m = dict(zip(f, sr.record)); a = m.get('ATTRIBUTE') or ''
            k = 'shore' if a in SHORE else 'marsh' if a in MARSH else None
            if not k: continue
            try: y = int(str(m.get('SRC_DATE'))[:4])
            except Exception: continue
            pts = sr.shape.points
            if len(pts) < 2: continue
            g = LineString(pts)
            if not g.intersects(BOX): continue
            g = g.intersection(BOX).simplify(0.00003)
            for part in (g.geoms if hasattr(g, 'geoms') else [g]):
                if part.geom_type != 'LineString' or len(part.coords) < 2: continue
                cc = [list(q) for q in part.coords]
                if k == 'shore' and ispier(cc): npier[0] += 1; continue
                if k == 'shore': cc = depier(cc, back=45)
                if len(cc) < 2: continue
                cc = LineString(chaikin(cc)).simplify(0.00002).coords
                rows.append({'e': era(y), 'y': y, 'k': k, 'c': [[round(x, 5), round(yy, 5)] for x, yy in cc]})
                n[(era(y), k)] = n.get((era(y), k), 0) + 1
    json.dump({'src': 'NOAA Coast Survey T-sheets via the NOAA Shoreline Data Explorer (Shoreline Data Rescue)', 'f': rows}, open(out, 'w'), separators=(',', ':'))
    print(npier[0], 'pier outlines dropped;', len(rows), 'lines', sorted(n.items()), os.path.getsize(out), 'bytes')


if __name__ == '__main__':
    main(*sys.argv[1:3])
