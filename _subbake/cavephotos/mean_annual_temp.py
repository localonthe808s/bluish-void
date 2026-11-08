"""1991-2020 mean annual air temperature at each notable cave (BLUISH VOID).

Source: Open-Meteo historical weather API (ERA5 / ERA5-Land reanalysis,
CC BY 4.0, https://open-meteo.com/en/docs/historical-weather-api):
  https://archive-api.open-meteo.com/v1/archive?latitude=..&longitude=..
    &start_date=1991-01-01&end_date=2020-12-31&daily=temperature_2m_mean
    &temperature_unit=fahrenheit
One call per cave, 3 s apart. Records the model elevation Open-Meteo reports
(it downscales to a 90 m DEM, which can still differ from a cave's
entrance). Written 2026-11-07.

usage: python3 -I mean_annual_temp.py caves_notable_v1.json OUT.json
"""
import json, sys, time, urllib.error, urllib.parse, urllib.request
UA = "bluishvoid.com (dashboard; cave photos)"
caves = json.load(open(sys.argv[1]))
try:
    out = json.load(open(sys.argv[2]))
except Exception:
    out = {}
for c in caves:
    if c["n"] in out:
        continue
    q = urllib.parse.urlencode({"latitude": c["lat"], "longitude": c["lon"],
        "start_date": "1991-01-01", "end_date": "2020-12-31",
        "daily": "temperature_2m_mean", "temperature_unit": "fahrenheit", "timezone": "GMT"})
    url = "https://archive-api.open-meteo.com/v1/archive?" + q
    for k in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                d = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code != 429: raise
            time.sleep(60 * (k + 1))
    v = [x for x in d["daily"]["temperature_2m_mean"] if x is not None]
    out[c["n"]] = {"mean_f": round(sum(v) / len(v), 2), "n_days": len(v), "elev_m": d.get("elevation"),
                   "grid_lat": d.get("latitude"), "grid_lon": d.get("longitude")}
    print(c["n"], out[c["n"]], flush=True)
    json.dump(out, open(sys.argv[2], "w"), indent=1)
    time.sleep(3)
