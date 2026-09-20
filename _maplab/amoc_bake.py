#!/usr/bin/env python3
"""AMOC at 26N, baked for the hurricane widget's OCEAN > AMOC view.

The Atlantic overturning is measured by ONE instrument: the RAPID-MOCHA-WBTS mooring array along
26.5N (National Oceanography Centre, UK, with NSF and NOAA). It is recovered from the sea floor
about every 18 months, so the record always ends one to two years ago -- there is no live AMOC
anywhere. The file is NetCDF (not something a browser reads), it changes about once a year, and it
is 1.2 MB of 12-hourly values: so it is baked to monthly means here and shipped as a few KB.

Run:  python3 _maplab/amoc_bake.py        (needs netCDF4 + numpy; re-run when RAPID publishes a new version)
Out:  _maplab/amoc_rapid.json
"""
import json, os, urllib.request, datetime as dt
import numpy as np, netCDF4 as nc

URL = 'https://rapid.ac.uk/sites/default/files/rapid_data/moc_transports.nc'
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(HERE, '_moc_transports.nc')

def main():
    urllib.request.urlretrieve(URL, TMP)
    d = nc.Dataset(TMP)
    t0 = dt.datetime(2004, 4, 1)
    days = np.array(d['time'][:], float)
    when = [t0 + dt.timedelta(days=float(x)) for x in days]
    def monthly(name):
        v = np.ma.filled(d[name][:].astype(float), np.nan); v[np.abs(v) > 1e3] = np.nan
        out, keys = [], []
        ym = [(w.year, w.month) for w in when]
        for k in sorted(set(ym)):
            m = np.array([x == k for x in ym]); vals = v[m]; vals = vals[~np.isnan(vals)]
            keys.append('%04d-%02d' % k); out.append(round(float(vals.mean()), 2) if len(vals) >= 20 else None)   # a month needs ~10 days of data
        return keys, out
    keys, moc = monthly('moc_mar_hc10')
    _, gs = monthly('t_gs10')
    while moc and moc[-1] is None: keys.pop(); moc.pop(); gs.pop()
    good = [x for x in moc if x is not None]
    out = {
        'source': 'RAPID-MOCHA-WBTS array, 26.5N', 'version': str(getattr(d, 'version', '')), 'url': 'https://rapid.ac.uk/',
        'ack': 'Data from the RAPID AMOC observing project is funded by the Natural Environment Research Council, U.S. National Science Foundation (NSF) with support from NOAA. They are freely available from https://rapid.ac.uk/',
        'unit': 'Sv (1 Sverdrup = 1 million cubic metres a second)', 'baked': dt.date.today().isoformat(),
        'months': keys, 'moc': moc, 'florida': gs, 'mean': round(float(np.mean(good)), 2),
    }
    d.close(); os.remove(TMP)
    json.dump(out, open(os.path.join(HERE, 'amoc_rapid.json'), 'w'), separators=(',', ':'))
    print('months', len(keys), keys[0], '->', keys[-1], '| mean', out['mean'], 'Sv | last', moc[-1], '| min', min(good), 'max', max(good), '| florida mean', round(float(np.nanmean([x for x in gs if x is not None])), 1))

if __name__ == '__main__':
    main()
