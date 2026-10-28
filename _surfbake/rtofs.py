#!/usr/bin/env python3
"""NOAA RTOFS-GLOBAL SURFACE CURRENTS (user 2026-10-28: "how can you improve the current flow visuals? are they accurate and real
time-ish?" -> "yes do all"). NOAA's operational global ocean model (HYCOM, 1/12 deg, run daily at 00Z, nowcast + 8-day
forecast), public domain, on AWS Open Data (noaa-nws-rtofs-pds). Unlike the satellite currents (geostrophic only, ~1 day
late), it carries the WIND-DRIVEN part and the hour: what a floating thing actually feels at the surface, today.

Where the surface velocity lives: not in the netCDF "2ds diag" files (those carry only the depth-averaged velocity) but in
the model's own surface archive, rtofs_glo.t00z.<n|f>HH.archs.{a.tgz,b}. The .b is a text list of fields; the .a is big-endian
float32, one field after another, each padded to a multiple of 4096 words; land is 2^100. In a HYCOM archive the layer
velocity is BAROCLINIC: the surface current = u-vel. (layer 1, the top ~1 m) + u_btrop. Both sit on the C-grid (u on the
west face, v on the south face) and along the grid's own axes, which turn north of ~47 N (the tripolar Arctic): averaged to
the cell centres and rotated to east / north with the angle the grid's own longitudes and latitudes give.

    python3 rtofs.py RUNDATE TAG [OUT.npz]      e.g. 20261027 n00   (n-24..n00 = the last day, f01..f192 = forecast)
"""
import io, os, sys, tarfile, urllib.request
import numpy as np

S3 = 'https://noaa-nws-rtofs-pds.s3.amazonaws.com/'
IDM, JDM = 4500, 3298
N = IDM * JDM
PAD = (N + 4095) // 4096 * 4096
SPIKE = 1e20
HERE = os.path.dirname(os.path.abspath(__file__))
GRID = os.path.join(os.environ.get('RTOFS_CACHE', os.path.expanduser('~/rtofs_bake')), 'grid.npz')


def http(url):
    for k in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bluish-void bake'}), timeout=300)
        except Exception as e:
            err = e
    raise SystemExit('RTOFS not reachable: %s (%s)' % (url, err))


def fields(b_text):
    out = []
    for line in b_text.splitlines():
        t = line.split()
        if len(t) >= 6 and t[1] == '=' and not t[0][0].isdigit() and not t[0].startswith("'"): out.append((t[0], int(t[4])))
    return out


def grid(day):
    """lon / lat of the cell centres, from a 2ds diag netCDF (cached: the grid never changes)"""
    if os.path.exists(GRID):
        g = np.load(GRID); return g['lon'], g['lat']
    import h5py
    os.makedirs(os.path.dirname(GRID), exist_ok=True)
    tmp = GRID + '.nc'
    if not os.path.exists(tmp):
        with http(S3 + 'rtofs.%s/rtofs_glo_2ds_f000_diag.nc' % day) as r, open(tmp, 'wb') as f:
            while True:
                b = r.read(1 << 22)
                if not b: break
                f.write(b)
    h = h5py.File(tmp, 'r'); lon = h['Longitude'][:].astype(np.float32); lat = h['Latitude'][:].astype(np.float32); h.close()
    np.savez(GRID, lon=lon, lat=lat); os.remove(tmp)
    return lon, lat


def surface(day, tag):
    """(u_east, v_north) at the cell centres, m/s, NaN on land"""
    base = S3 + 'rtofs.%s/rtofs_glo.t00z.%s.archs' % (day, tag)
    with http(base + '.b') as r: fl = fields(r.read().decode('latin-1'))
    names = [f[0] for f in fl]
    want = {'u_btrop': names.index('u_btrop'), 'v_btrop': names.index('v_btrop'), 'u-vel.': names.index('u-vel.'), 'v-vel.': names.index('v-vel.')}
    last = max(want.values())
    got = {}
    with http(base + '.a.tgz') as r:
        tf = tarfile.open(fileobj=r, mode='r|gz')
        for m in tf:
            if not m.name.endswith('.a'): continue
            fa = tf.extractfile(m)
            for i in range(last + 1):
                buf = fa.read(PAD * 4)
                if len(buf) < PAD * 4: raise SystemExit('short archive')
                k = [kk for kk, ii in want.items() if ii == i]
                if k:
                    a = np.frombuffer(buf[:N * 4], dtype='>f4').astype(np.float32).reshape(JDM, IDM)
                    a = np.where(np.abs(a) > SPIKE, np.nan, a); got[k[0]] = a
            break
    u = got['u-vel.'] + got['u_btrop']; v = got['v-vel.'] + got['v_btrop']
    # C-grid to centres (u: west face of cell i; v: south face of row j)
    uc = np.full_like(u, np.nan); vc = np.full_like(v, np.nan)
    uc[:, :-1] = (u[:, :-1] + u[:, 1:]) / 2; uc[:, -1] = (u[:, -1] + u[:, 0]) / 2
    vc[:-1, :] = (v[:-1, :] + v[1:, :]) / 2; vc[-1, :] = v[-1, :]
    lon, lat = grid(day)
    # the grid's i-axis bearing: from the neighbour's lon / lat (east, north components of a step along i)
    dlon = np.roll(lon, -1, axis=1) - np.roll(lon, 1, axis=1); dlon = (dlon + 540) % 360 - 180
    dlat = np.roll(lat, -1, axis=1) - np.roll(lat, 1, axis=1)
    ang = np.arctan2(dlat, dlon * np.cos(np.radians(lat)))
    ca, sa = np.cos(ang), np.sin(ang)
    ue = uc * ca - vc * sa; vn = uc * sa + vc * ca
    return lon, lat, ue.astype(np.float32), vn.astype(np.float32)


def regrid(lon, lat, u, v, res=0.25):
    """onto a plain lat/lon grid (rows south -> north, cols -180 -> 180), the mean of the model cells in each box"""
    W, H = int(360 / res), int(180 / res)
    ok = np.isfinite(u) & np.isfinite(v)
    lo = ((lon[ok] + 180) % 360) - 180; la = lat[ok]
    ix = np.clip(((lo + 180) / res).astype(np.int64), 0, W - 1); iy = np.clip(((la + 90) / res).astype(np.int64), 0, H - 1)
    k = iy * W + ix
    n = np.bincount(k, minlength=W * H); su = np.bincount(k, u[ok], minlength=W * H); sv = np.bincount(k, v[ok], minlength=W * H)
    with np.errstate(invalid='ignore', divide='ignore'):
        U = np.where(n > 0, su / n, np.nan).reshape(H, W); V = np.where(n > 0, sv / n, np.nan).reshape(H, W)
    return U.astype(np.float32), V.astype(np.float32)


if __name__ == '__main__':
    day, tag = sys.argv[1], sys.argv[2]
    lon, lat, u, v = surface(day, tag)
    U, V = regrid(lon, lat, u, v)
    sp = np.hypot(U, V)
    print(day, tag, 'cells', np.isfinite(sp).sum(), 'max %.2f p99 %.2f m/s' % (np.nanmax(sp), np.nanpercentile(sp, 99)))
    if len(sys.argv) > 3: np.savez_compressed(sys.argv[3], U=U, V=V)
