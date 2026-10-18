#!/usr/bin/env python3
"""A SEASON OF WEEKLY FRAMES FOR THE NATIONAL FOLIAGE MAP (2026-10-17). The Northeast bake's season_frames() and
last_year_curve()/county_last_year() (_maplab/foliage_bake.py) over na.py's blocks: for each week Sep 15 - Dec 1 of YEAR
the index from that date's composite and the one six days before, against YEAR's own August baseline, on the cached
forest mask; written as a tile pyramid OUT/season/YEAR/DATE/{z}/{x}/{y}.webp (z3-8), and the region and county means of
every week as SEASON_BASE/season_YEAR.json ({dates, regions: {name: [pct...]}, counties: {fips: [pct...]}}), which na.py
reads as a seed. Resumable: a block-week whose grid is on disk is not fetched again.

    python3 na_season.py YEAR OUT SEASON_BASE FOREST_BASE [UPTO]
FOREST_BASE is na.py's cache (b_*.npz with the forest mask; l_*.npz county labels). SEASON_BASE holds YEAR's baseline
(b_*.npz with only 'base') and the weekly grids; pass FOREST_BASE itself for the current year to reuse its baseline.
"""
import datetime, json, os, sys
import numpy as np
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import na


def main():
    year = int(sys.argv[1]); out = sys.argv[2]; sbase = sys.argv[3]; fbase = sys.argv[4]
    upto = datetime.date.fromisoformat(sys.argv[5]) if len(sys.argv) > 5 else None
    os.makedirs(sbase, exist_ok=True)
    dates = na.season_dates(year, upto)
    aug = [datetime.date(year, 8, d) for d in na.AUG_DAYS]
    blocks = []
    for bx, by in na.all_blocks():
        f = os.path.join(fbase, 'b_%d_%d.npz' % (bx, by))
        if os.path.exists(f) and np.load(f)['base'].size > 1: blocks.append((bx, by))
    print('season %d: %d weeks x %d blocks' % (year, len(dates), len(blocks)), flush=True)

    def work(b):
        bx, by = b; bb = na.bbox_of(bx, by, na.BLK, na.BLK)
        fz = np.load(os.path.join(fbase, 'b_%d_%d.npz' % (bx, by))); fm = fz['forest']
        todo = [d for d in dates if not os.path.exists(os.path.join(sbase, 'p_%s_%d_%d.npy' % (d.isoformat(), bx, by)))]
        if not todo: return
        if os.path.abspath(sbase) == os.path.abspath(fbase):
            base = fz['base'].astype(np.float32) / 250
        else:
            cache = os.path.join(sbase, 'b_%d_%d.npz' % (bx, by))
            if os.path.exists(cache):
                base = np.load(cache)['base'].astype(np.float32) / 250
            else:
                base = na.baseline(bb, aug)
                if base is None: print('block', bx, by, 'no baseline'); return
                np.savez_compressed(cache, base=np.nan_to_num(np.clip(base, 0, 1) * 250).astype(np.uint8))
                base = np.round(np.nan_to_num(np.clip(base, 0, 1)) * 250) / 250
        for d in todo:
            p = na.progress(bb, base, fm, (d, d - datetime.timedelta(days=6)))
            if p is None: print('block', bx, by, d, 'no composite', flush=True); continue
            np.save(os.path.join(sbase, 'p_%s_%d_%d.npy' % (d.isoformat(), bx, by)), na.to_u8(p))
        print('block', bx, by, 'done', flush=True)
    with ThreadPoolExecutor(4) as ex: list(ex.map(work, blocks))

    ids = json.load(open(os.path.join(fbase, 'l_ids.json')))
    have, regions, counties = [], {n: [] for n, *_ in na.REGIONS}, {f: [] for f in ids}
    for d in dates:
        grids = {(bx, by): os.path.join(sbase, 'p_%s_%d_%d.npy' % (d.isoformat(), bx, by)) for bx, by in blocks}
        grids = {k: v for k, v in grids.items() if os.path.exists(v)}
        if len(grids) < 0.8 * len(blocks): print(d, 'too few blocks', len(grids)); continue
        dst = os.path.join(out, 'season', str(year), d.isoformat())
        if not os.path.isdir(os.path.join(dst, '3')):
            n = 0
            for (bx, by), f in grids.items(): n += na.block_tiles(na.from_u8(np.load(f)), bx, by, dst)
            print(d, 'z%d:' % na.Z, n, 'tiles', flush=True)
            na.pyramid(grids, dst)
        rm = na.region_means(grids); cm = na.county_means(grids, fbase, ids)
        have.append(d.isoformat())
        for n in regions: regions[n].append(rm.get(n, (None, None))[0])
        for f in counties: counties[f].append(cm.get(f))
        print(d, 'regions', len(rm), 'counties', len(cm), flush=True)
    counties = {f: v for f, v in counties.items() if any(x is not None for x in v)}
    json.dump({'year': year, 'dates': have, 'regions': regions, 'counties': counties},
              open(os.path.join(sbase, 'season_%d.json' % year), 'w'), separators=(',', ':'))
    print('wrote season_%d.json: %d weeks' % (year, len(have)))


if __name__ == '__main__':
    main()
