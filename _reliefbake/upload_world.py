#!/usr/bin/env python3
"""After bake_world.py: push the world pyramids to R2 (2026-10-26).
  relief/v1, seafloor/v1: keep North America's own z8 index as cover_na.json (once -- the page uses it to tell NA's deep cells from
  the world's), copy the world's z3-ZMAX tiles over (at z8 and coarser the AWS Terrain Tiles and 3DEP are the same picture, and the
  world tiles are whole where NA's edge tiles were cut at its boxes), cover.json = NA's index joined with the world's.
  bathy/world1: the depth tint and its own cover.json.
    python3 upload_world.py /Users/vvvaa/relief_bake/world [--zmax 8]
"""
import json, os, subprocess, sys, tempfile
W = sys.argv[1]; ZMAX = int(sys.argv[sys.argv.index('--zmax') + 1]) if '--zmax' in sys.argv else 8
R = 'r2:bluishvoid-bg/'; FL = ['--s3-no-check-bucket', '--transfers', '32', '--checkers', '32', '--fast-list']
def rc(*a): print('rclone', *a[:3], flush=True); subprocess.run(['rclone'] + list(a) + FL, check=True)
def z8cells(mode):
    """z8 cells holding a world tile: the has-file's z8 rows (every deeper tile sits under one)"""
    return {'/'.join(l.split('/')[1:3]) for l in open(os.path.join(W, mode, mode + '_has.txt')).read().split() if l.startswith('8/')}
tmp = tempfile.mkdtemp()
for mode, pre, cov in (('land', 'relief/v1', 'cover.json'), ('sea', 'seafloor/v1', 'cover.json')):
    na = os.path.join(tmp, mode + '_na.json')
    r = subprocess.run(['rclone', 'lsf', R + pre + '/cover_na.json'], capture_output=True, text=True)
    if not r.stdout.strip():
        subprocess.run(['rclone', 'copyto', R + pre + '/' + cov, na, '--s3-no-check-bucket'], check=True)
        rc('copyto', na, R + pre + '/cover_na.json', '--header-upload', 'Cache-Control: public, max-age=3600')
    else:
        subprocess.run(['rclone', 'copyto', R + pre + '/cover_na.json', na, '--s3-no-check-bucket'], check=True)
    inc = sum([['--include', '/%d/**' % z] for z in range(3, ZMAX + 1)], [])
    rc('copy', os.path.join(W, mode), R + pre, *inc, '--header-upload', 'Cache-Control: public, max-age=86400')
    merged = sorted(set(json.load(open(na))) | z8cells(mode))
    p = os.path.join(tmp, mode + '_cover.json'); json.dump(merged, open(p, 'w'), separators=(',', ':'))
    rc('copyto', p, R + pre + '/' + cov, '--header-upload', 'Cache-Control: public, max-age=3600')
    print(pre, 'cover', len(merged), 'cells', flush=True)
inc = sum([['--include', '/%d/**' % z] for z in range(3, ZMAX + 1)], [])
rc('copy', os.path.join(W, 'depth'), R + 'bathy/world1', *inc, '--header-upload', 'Cache-Control: public, max-age=86400')
p = os.path.join(tmp, 'depth_cover.json'); json.dump(sorted(z8cells('depth')), open(p, 'w'), separators=(',', ':'))
rc('copyto', p, R + 'bathy/world1/cover.json', '--header-upload', 'Cache-Control: public, max-age=3600')
print('DONE', flush=True)
