#!/usr/bin/env python3
"""TREE RINGS, THE SITES (user 2026-10-29: "lets add this info ... TREES with two subtabs FOLIAGE & ... a new tab"). Every ITRDB tree-ring
study in North America from NOAA NCEI's paleo search API (public domain): site, point, species, the years it spans, the standard
chronology file. The page reads a site's chronology straight from NCEI (CORS open) when it is shown.
    python3 _ringbake/index.py OUT.json        -> cdn rings/sites_v1.json"""
import json, re, sys, time, urllib.request
API = 'https://www.ncei.noaa.gov/access/paleo-search/study/search.json?dataTypeId=18&searchText=ITRDB&minLat=%g&maxLat=%g&minLon=%g&maxLon=%g'
SP = {'QUAL':'WHITE OAK','QUSP':'OAK','QURU':'RED OAK','QUPR':'CHESTNUT OAK','QUMO':'CHESTNUT OAK','QUST':'POST OAK','TSCA':'EASTERN HEMLOCK','PIRU':'RED SPRUCE',
 'PIST':'WHITE PINE','PIRE':'RED PINE','PIRI':'PITCH PINE','JUVI':'EASTERN RED CEDAR','LITU':'TULIP POPLAR','CAGL':'PIGNUT HICKORY','TADI':'BALD CYPRESS',
 'PSME':'DOUGLAS FIR','PIPO':'PONDEROSA PINE','PILO':'BRISTLECONE PINE','PIFL':'LIMBER PINE','PIED':'PINYON PINE','JUOC':'WESTERN JUNIPER','SEGI':'GIANT SEQUOIA',
 'TSME':'MOUNTAIN HEMLOCK','PCGL':'WHITE SPRUCE','PCMA':'BLACK SPRUCE','PCEN':'ENGELMANN SPRUCE','ABLA':'SUBALPINE FIR','LALA':'TAMARACK','THOC':'NORTHERN WHITE CEDAR',
 'PIBA':'JACK PINE','PIEC':'SHORTLEAF PINE','PITA':'LOBLOLLY PINE','PIPA':'LONGLEAF PINE','CHNO':'ALASKA YELLOW CEDAR','PCSI':'SITKA SPRUCE','LAOC':'WESTERN LARCH',
 'PIAL':'WHITEBARK PINE','PIBR':'BRISTLECONE PINE','PILA':'SUGAR PINE','PIJE':'JEFFREY PINE','JUSC':'ROCKY MOUNTAIN JUNIPER','QUDG':'BLUE OAK','QULO':'VALLEY OAK',
 'FRNI':'BLACK ASH','ACSH':'SUGAR MAPLE','ACSA':'SUGAR MAPLE','BELE':'SWEET BIRCH','FAGR':'AMERICAN BEECH','PCRU':'RED SPRUCE','THPL':'WESTERN RED CEDAR'}
def get(u):
    for k in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'bluish-void bake'}), timeout=180))
        except Exception as e: err = e; time.sleep(4)
    raise SystemExit('paleo search failed: %s' % err)
def main(out):
    rows = {}
    for la in range(14, 72, 8):
        for lo in range(-170, -50, 10):
            d = get(API % (la, la + 8, lo, lo + 10))
            for s in d.get('study', []):
                nm = s.get('studyName', ''); m = re.search(r'ITRDB\s+([A-Z]{2,4}\d{2,4}[A-Z]?)', nm)
                if not m: continue
                code = m.group(1).lower()
                for st in s.get('site', []):
                    try: c = st['geo']['geometry']['coordinates']; lat, lon = float(c[0]), float(c[1])
                    except Exception: continue
                    crn = None
                    for pd in st.get('paleoData', []):
                        for f in pd.get('dataFile', []):
                            u = f.get('fileUrl') or ''
                            if u.endswith('/%s.crn' % code): crn = u
                    if not crn: continue
                    spc = (re.search(r' - ([A-Z]{4}) - ITRDB', nm) or [None, ''])[1]
                    try: y0, y1 = int(s.get('earliestYearCE')), int(s.get('mostRecentYearCE'))
                    except Exception: continue
                    # TIMBERS, NOT TREES THAT GREW HERE (2026-10-29): beams from buildings and wrecks were cut elsewhere and record that place's weather
                    txt = ' '.join([nm, st.get('siteName', ''), (s.get('studyNotes') or '')[:600]])
                    hist = bool(re.search(r'\b(building|warehouse|barn|house|church|mill|hall|timbers?|historic(al)?|archaeolog\w*|beams?|structure|cabin|fort|tavern|shipwreck|ship|log ?cabin|bridge|courthouse|homestead|farmstead)\b', txt, re.I))
                    rows[code] = {'h': 1 if hist else 0, 'c': code, 'n': st.get('siteName', '').strip(), 'la': round(lat, 3), 'lo': round(lon, 3), 'sp': SP.get(spc, spc), 'y0': y0, 'y1': y1,
                                  'u': crn.replace('https://www.ncei.noaa.gov/pub/data/paleo/treering/', ''), 'by': (s.get('investigators') or '').split(';')[0].strip()}
            time.sleep(0.3)
        print(la, len(rows), flush=True)
    L = sorted(rows.values(), key=lambda r: r['y0'])
    json.dump({'src': 'International Tree-Ring Data Bank, NOAA NCEI (public domain)', 'base': 'https://www.ncei.noaa.gov/pub/data/paleo/treering/', 'f': L}, open(out, 'w'), separators=(',', ':'))
    print(len(L), 'sites')
if __name__ == '__main__': main(sys.argv[1])
