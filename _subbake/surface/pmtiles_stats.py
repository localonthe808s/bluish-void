"""Per-zoom tile-size stats for a local PMTiles v3 file: python3 pmtiles_stats.py FILE [z/x/y ...]
With tile ids, prints per-layer feature counts of those tiles (needs mapbox_vector_tile)."""
import gzip, io, struct, sys

def varint(b, i):
    r = s = 0
    while True:
        c = b[i]; i += 1; r |= (c & 0x7F) << s; s += 7
        if c < 0x80: return r, i

def read_dir(b):
    i = 0; n, i = varint(b, i); ids = []; last = 0
    for _ in range(n):
        d, i = varint(b, i); last += d; ids.append(last)
    rl = [];  ln = []; off = []
    for _ in range(n): v, i = varint(b, i); rl.append(v)
    for _ in range(n): v, i = varint(b, i); ln.append(v)
    for k in range(n):
        v, i = varint(b, i); off.append(off[k-1] + ln[k-1] if v == 0 and k > 0 else v - 1)
    return list(zip(ids, rl, off, ln))

def zxy(t):
    acc = 0
    for z in range(32):
        n = (1 << z) ** 2
        if t < acc + n:
            p = t - acc; x = y = 0; s = 1
            nn = 1 << z
            while s < nn:  # hilbert d2xy
                rx = 1 & (p // 2); ry = 1 & (p ^ rx)
                if ry == 0:
                    if rx == 1: x, y = s - 1 - x, s - 1 - y
                    x, y = y, x
                x += s * rx; y += s * ry; p //= 4; s *= 2
            return z, x, y
        acc += n

def tiles(f):
    h = f.read(127); f.seek(0)
    rd_off, rd_len, _, _, ld_off, ld_len, td_off = struct.unpack("<7Q", h[8:64])
    comp = h[97]
    dec = (lambda x: gzip.decompress(x)) if comp == 2 else (lambda x: x)
    def get(o, l): f.seek(o); return f.read(l)
    out = []
    def walk(o, l):
        for tid, rl, off, ln in read_dir(dec(get(o, l))):
            if rl == 0: walk(ld_off + off, ln)
            else:
                for k in range(rl): out.append((tid + k, td_off + off, ln))
    walk(rd_off, rd_len); return out, get, h[98]

if __name__ == "__main__":
    with open(sys.argv[1], "rb") as f:
        ts, get, tcomp = tiles(f)
        by = {}
        for tid, o, l in ts:
            z, x, y = zxy(tid); by.setdefault(z, []).append((l, x, y))
        for z in sorted(by):
            ls = sorted(by[z]); n = len(ls)
            print("z%-2d tiles %7d  median %6.1fKB  p95 %6.1fKB  max %6.1fKB @%d/%d/%d" % (
                z, n, ls[n//2][0]/1e3, ls[int(n*.95)][0]/1e3, ls[-1][0]/1e3, z, ls[-1][1], ls[-1][2]))
        if len(sys.argv) > 2:
            import mapbox_vector_tile as M
            idx = {zxy(t): (o, l) for t, o, l in ts}
            for a in sys.argv[2:]:
                k = tuple(map(int, a.split("/")))
                if k not in idx: print(a, "absent"); continue
                d = get(*idx[k]); d = gzip.decompress(d) if tcomp == 2 else d
                t = M.decode(d)
                print(a, {n: len(v["features"]) for n, v in t.items()},
                      {n: (v["features"][0]["properties"] if v["features"] else None) for n, v in t.items()})
