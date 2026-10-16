#!/usr/bin/env python3
"""NWS alert zones for every state, for the LOCAL radar's warnings (user 2026-10-16: "the charleston radar should have
hazards showing ... like NYC"). Most NWS alerts are ZONE-based and carry no polygon, and a single zone's live geometry
from api.weather.gov can be 1.25 MB (NCZ196, the Outer Banks), so the outlines are baked once from the NWS's own
shapefiles, the way city_ne_zones.json was for THE CITY:
    z_DDmmYY  public forecast zones  -> UGC  ST + 'Z' + ZONE   (SCZ050)
    c_DDmmYY  counties               -> UGC  ST + 'C' + FIPS[2:] (SCC019)
Simplified to ~500 m, coordinates to 3 decimals, outer rings only. One file per state plus states.json, the bounding
box of each, so the page fetches only the states its map touches.

    python3 bake.py ZONES.shp COUNTIES.shp OUTDIR      # then: rclone copy OUTDIR r2:bluishvoid-bg/zones/v1
"""
import json, os, sys
import shapefile
from shapely.geometry import shape

TOL = 0.005

def rings(geom):
    g = shape(geom).simplify(TOL, preserve_topology=True)
    polys = [g] if g.geom_type == 'Polygon' else list(getattr(g, 'geoms', []))
    out = []
    for p in polys:
        if p.is_empty or p.area < 1e-6: continue
        out.append([[round(x, 3), round(y, 3)] for x, y in p.exterior.coords])
    return out

def main(zshp, cshp, out):
    os.makedirs(out, exist_ok=True)
    per, box = {}, {}
    def add(st, ugc, geom):
        rr = rings(geom)
        if not rr: return
        d = per.setdefault(st, {})
        d[ugc] = d.get(ugc, []) + rr
        xs = [p[0] for r in rr for p in r]; ys = [p[1] for r in rr for p in r]
        b = box.get(st, [999, 999, -999, -999])
        box[st] = [min(b[0], min(xs)), min(b[1], min(ys)), max(b[2], max(xs)), max(b[3], max(ys))]
    for sr in shapefile.Reader(zshp).iterShapeRecords():
        r = sr.record.as_dict()
        add(r['STATE'], r['STATE'] + 'Z' + r['ZONE'], sr.shape.__geo_interface__)
    for sr in shapefile.Reader(cshp).iterShapeRecords():
        r = sr.record.as_dict()
        add(r['STATE'], r['STATE'] + 'C' + r['FIPS'][2:], sr.shape.__geo_interface__)
    tot = 0
    for st, d in per.items():
        p = os.path.join(out, st + '.json')
        json.dump(d, open(p, 'w'), separators=(',', ':')); tot += os.path.getsize(p)
    json.dump({k: [round(v, 2) for v in b] for k, b in box.items()}, open(os.path.join(out, 'states.json'), 'w'), separators=(',', ':'))
    print(len(per), 'states', sum(len(d) for d in per.values()), 'zones', round(tot / 1e6, 1), 'MB')

if __name__ == '__main__':
    main(*sys.argv[1:4])
