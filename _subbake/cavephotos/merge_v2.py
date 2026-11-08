"""Build caves_notable_v2.json for the CAVES tab (BLUISH VOID), 2026-11-07.

v1 fields are copied unchanged; added per cave:
  photo, credit, photo_src   from build_photos.py (Wikimedia Commons, PD/CC0/CC BY/CC BY-SA)
  t_f, t_src, t_src_url      typical temperature deep inside, deg F
  t_note                     caveat, only where one is needed
Temperature rule: a published figure (NPS, operator, park, paper, Wikipedia;
gathered 2026-11-07 into published_temps.json with its URL) wins when it is
judged usable (REJECT below lists the ones that are not); otherwise the
1991-2020 mean annual air temperature from Open-Meteo's ERA5 archive
(mean_annual_temp.py -> mat.json).

usage: python3 -I merge_v2.py v1.json photos.json published_temps.json mat.json OUT.json
"""
import json, sys
v1, photos, pub, mat = (json.load(open(p)) for p in sys.argv[1:5])
pub = {x["n"]: x for x in pub}
COMPUTED = "computed: 1991-2020 mean annual air temperature (ERA5 via Open-Meteo)"
# published figures not used, and why (computed value used instead)
REJECT = {
    "Toca da Boa Vista": "only an 'up to 30 C' upper bound from an old Wikipedia snapshot",
    "Cueva del Viento": "travel-site figures conflict (15 C vs 18-20 C)",
}
# no figure for this cave, but a sound proxy exists
PROXY = {
    "Fisher Ridge Cave System": (54, "proxy: NPS deep-cave figure for adjacent Mammoth Cave (54 F)",
                                 "https://www.nps.gov/maca/faqs.htm",
                                 "no published figure; ERA5 mean at the site is 57.8 F, which reads ~4 F warm at Mammoth"),
}
# caveats on computed values
CNOTE = {
    "Snezhnaya (Tovliani) Cave": "high-mountain entrance (~1970 m); deep levels likely a few degrees warmer",
    "Gouffre Berger": "entrance-elevation air mean; deep levels likely a few degrees warmer",
    "Sarawak Chamber": "ERA5 grid at ~715 m; chamber lies lower, so likely slightly warmer",
    "Miao Room": "no published figure; underground river cave",
    "Kazumura Cave": "tube spans ~1100 m to near sea level; value is for the mapped point",
    "Cueva del Viento": "published figures conflict (15 C vs 18-20 C)",
    "Toca da Boa Vista": "explorers report up to 30 C (86 F) inside",
    "Fingal's Cave": "open sea cave: inside follows the outside air",
    "Blue Grotto": "open sea cave: inside follows the outside air and sea",
    "Sea Lion Caves": "open sea cave: operator says only 'cool all year'",
    "Painted Cave": "open sea cave: inside follows the outside air and sea",
    "Leang Tedongnge": "shallow rock-art cave: close to outside air",
    "Cueva de las Manos": "open rock shelter: inside is the outside air",
    "Cosquer Cave": "monitored, but no published value found",
    "Natural Stone Bridge and Caves": "stream and boulder caves: closer to outside air, cooler in summer",
    "Sam's Point Ice Caves": "talus ice cave: colder than this; ice often lasts into summer",
    "Lost River Gorge and Boulder Caves": "boulder caves: colder than this; operator posts daily gorge readings",
    "Polar Caves": "talus caves: colder than this; ice lingers to about August",
    "Clearwater Cave": "no published figure; lowland tropical cave",
    "Deer Cave": "no published figure; lowland tropical cave",
}
out = []
for c in v1:
    r = dict(c)
    n = c["n"]
    r.update({k: v for k, v in photos.get(n, {}).items() if not k.startswith("_")})
    p = pub.get(n)
    if n in PROXY:
        t, src, url, note = PROXY[n]
        r.update(t_f=t, t_src=src, t_src_url=url, t_note=note)
    elif p and p.get("t_f") is not None and n not in REJECT:
        r.update(t_f=round(p["t_f"]), t_src=f"published: {p['orig']} ({p['src_name']})", t_src_url=p["src_url"])
        if p.get("note"):
            r["t_note"] = p["note"]
    else:
        r.update(t_f=round(mat[n]["mean_f"]), t_src=COMPUTED, t_src_url="https://open-meteo.com/en/docs/historical-weather-api")
        if n in CNOTE:
            r["t_note"] = CNOTE[n]
    out.append(r)
json.dump(out, open(sys.argv[5], "w"), indent=1, ensure_ascii=False)
print(len(out), "caves;", sum("photo" in r for r in out), "photos;",
      sum(r["t_src"].startswith("published") for r in out), "published temps")
