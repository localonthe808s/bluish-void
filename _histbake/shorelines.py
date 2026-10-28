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


def era(y):
    return 1880 if y < 1895 else 1910 if y < 1920 else 1935


def main(src, out):
    rows = []; n = {}
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
                rows.append({'e': era(y), 'y': y, 'k': k, 'c': [[round(x, 5), round(yy, 5)] for x, yy in part.coords]})
                n[(era(y), k)] = n.get((era(y), k), 0) + 1
    json.dump({'src': 'NOAA Coast Survey T-sheets via the NOAA Shoreline Data Explorer (Shoreline Data Rescue)', 'f': rows}, open(out, 'w'), separators=(',', ':'))
    print(len(rows), 'lines', sorted(n.items()), os.path.getsize(out), 'bytes')


if __name__ == '__main__':
    main(*sys.argv[1:3])
