#!/usr/bin/env python3
"""THE MAP STYLE'S FINGERPRINT (2026-10-24).

The baked maps -- /radarmaps/*.jpg (NATIONWIDE and the far regions) and cdn radarmaps/sta/<style>/<station>.jpg (NEAREST) --
are pictures of what index.html's style code draws. That code is fenced in index.html with /*MAPSTYLE{*/ ... /*}MAPSTYLE*/
(the flavours and continental config, the overlay pyramids' URLs, the region boxes, the station box, the stitcher). This
hashes the fenced text (whitespace-insensitive), so a change there gives a new fingerprint and mapstyle-bake.yml re-bakes.

    python3 _maplab/mapstyle.py            # print the fingerprint of the code as it is
    python3 _maplab/mapstyle.py --check    # exit 1 when it differs from window.BV_MAPSTYLE (a re-bake is due)
    python3 _maplab/mapstyle.py --write    # set window.BV_MAPSTYLE to it (after the new set is uploaded)
"""
import hashlib, os, re, sys

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'index.html')
SET = re.compile(r"window\.BV_MAPSTYLE = '([^']*)';")


def fingerprint(src):
    parts = re.findall(r'/\*MAPSTYLE\{\*/(.*?)/\*\}MAPSTYLE\*/', src, re.S)
    if len(parts) < 5: raise SystemExit('MAPSTYLE fences missing (%d found)' % len(parts))
    norm = '\n'.join(re.sub(r'\s+', ' ', p).strip() for p in parts)
    return 's' + hashlib.sha1(norm.encode('utf-8')).hexdigest()[:10]


def main():
    src = open(P, encoding='utf-8').read()
    fp = fingerprint(src)
    cur = SET.search(src)
    if '--check' in sys.argv:
        print('style %s, page loads %s' % (fp, cur.group(1) if cur else None))
        sys.exit(0 if cur and cur.group(1) == fp else 1)
    if '--write' in sys.argv:
        if not cur: raise SystemExit('window.BV_MAPSTYLE not found')
        open(P, 'w', encoding='utf-8').write(src[:cur.start()] + "window.BV_MAPSTYLE = '%s';" % fp + src[cur.end():])
    print(fp)


if __name__ == '__main__':
    main()
