"""THE ICE'S LEAVINGS on the CITY MAP's GEOLOGY tab (2026-10-12, user: "do these" -- kettle ponds, erratics as tappable points,
the ice-flow direction from the striations; Cameron's Line was already a traced fault and only gains its name on the map).
Every site comes from a published source, named per entry; positions from OSM where OSM has them, else the source's own
coordinates (Wikipedia/Wikidata). Nothing is placed from memory.
  kettle[] : ponds the sources call KETTLE PONDS, outlines from OSM (osm_kettles.json: Overpass, natural=water by name)
             - Alley Pond Park: "seven ponds ... all of which are kettle ponds" + Oakland Lake (Wikipedia, Alley Pond Park);
               OSM outlines exist for Alley Pond, Little Alley Pond, Turtle Pond, Lily Pad Pond, Oakland Lake
             - Forest Park: Strack Pond, "a glacial kettle pond" (Wikipedia, Strack Pond / Forest Park)
  gone[]   : Jackson Pond, Forest Park -- a kettle "infilled in 1966" (Wikipedia, Forest Park); point = OSM Jackson Pond Playground
  rock[]   : erratics (k 'e') and ice-carved bedrock (k 's')
  flow[]   : the ice's direction. Merguerian, Central Park field guide (AIPG 2009 / CMMM 2004, dukelabs.com): the dominant
             glacial features "were caused by a thick glacier that flowed across Manhattan from about N30W to S30E";
             Sanders & Merguerian 1991 also describe an ice advance from NNE to SSW down the Hudson.
python3 glacial_bake.py <osm_kettles.json> <out.json>"""
import sys, json
O = json.load(open(sys.argv[1]))['elements']
KETTLE = {'Alley Pond': 'Alley Pond Park', 'Little Alley Pond': 'Alley Pond Park', 'Turtle Pond': 'Alley Pond Park',
          'Lily Pad Pond': 'Alley Pond Park', 'Oakland Lake': 'Alley Pond Park', 'Strack Pond': 'Forest Park'}
out = {'src': 'kettles: Wikipedia (Alley Pond Park, Forest Park, Strack Pond) + OSM outlines; erratics: Wikipedia (Pelham Bay Park, '
              'Rat Rock), Wikidata, OSM; ice flow: Merguerian, Central Park field guide; Sanders & Merguerian 1991',
       'kettle': [], 'gone': [], 'rock': [], 'flow': []}
for e in O:
    t = e.get('tags', {}); n = t.get('name')
    if e['type'] == 'way' and n in KETTLE and (t.get('natural') == 'water'):
        if n == 'Turtle Pond' and e['geometry'][0]['lon'] > -73.9 and e['geometry'][0]['lat'] > 40.77: continue   # not Central Park's
        r = [v for p in e['geometry'] for v in (round(p['lon'], 6), round(p['lat'], 6))]
        out['kettle'].append({'n': n, 'park': KETTLE[n], 'r': r,
                              'note': 'A KETTLE POND: A HOLLOW LEFT WHERE A BLOCK OF ICE, BURIED IN THE MORAINE’S RUBBLE, MELTED'
                                      + (' · BURIED IN 1966, DUG OUT AGAIN FOUR DECADES LATER' if n == 'Strack Pond' else '')})
out['gone'].append({'n': 'Jackson Pond', 'park': 'Forest Park', 'c': [-73.84356, 40.70092],
                    'note': 'A KETTLE POND, FILLED IN IN 1966 · A PLAYGROUND NOW'})
out['rock'] = [
    {'k': 'e', 'n': 'Glover’s Rock', 'c': [-73.80336, 40.86491], 'src': 'OSM node 9826075393; Wikipedia, Pelham Bay Park',
     'note': 'A GIANT GRANITE ERRATIC, CARRIED HERE BY THE ICE · ITS PLAQUE NAMES THE BATTLE OF PELL’S POINT, THOUGH THE ROCK HAD NO PART IN IT'},
    {'k': 'e', 'n': 'Split Rock', 'c': [-73.81496, 40.88651], 'src': 'OSM node 7509328585; Wikipedia, Pelham Bay Park',
     'note': 'A GRANITE BOULDER, MOST LIKELY AN ERRATIC, SPLIT INTO TWO HALF DOMES · ANNE HUTCHINSON’S SETTLEMENT WAS NEAR HERE'},
    {'k': 's', 'n': 'Rat Rock (Umpire Rock)', 'c': [-73.977655, 40.769361], 'src': 'Wikipedia, Rat Rock (Central Park)',
     'note': 'MANHATTAN SCHIST SCRATCHED BY THE ICE · CENTRAL PARK’S STRIATIONS RUN NORTHWEST TO SOUTHEAST'},
    {'k': 's', 'n': 'Ancient Glacier Rock', 'c': [-73.94816, 40.75041], 'src': 'OSM node 6783868234; Wikidata Q124243754 (roche moutonnée)',
     'note': 'BEDROCK SMOOTHED AND PLUCKED BY THE PASSING ICE (A ROCHE MOUTONNÉE)'},
    {'k': 's', 'n': 'Twin Island', 'c': [-73.784389, 40.871186], 'src': 'Wikipedia, Pelham Bay Park',
     'note': 'BARE BEDROCK CUT WITH GLACIAL GROOVES · THE SHORE AROUND IT IS STREWN WITH ERRATICS'},
]
# the measured direction, drawn where it was measured: across Manhattan, toward S30E (bearing 150)
out['flow'] = [{'c': c, 'brg': 150} for c in ([-73.9655, 40.7800], [-73.9420, 40.8350], [-74.0010, 40.7500])]
out['flowNote'] = ('THE ICE MOVED NORTHWEST TO SOUTHEAST ACROSS MANHATTAN, READ FROM THE STRIATIONS (MERGUERIAN) · '
                   'A LATER ADVANCE CAME DOWN THE HUDSON FROM THE NORTH-NORTHEAST (SANDERS & MERGUERIAN 1991)')
json.dump(out, open(sys.argv[2], 'w'), separators=(',', ':'), ensure_ascii=False)
print([k['n'] for k in out['kettle']], len(out['rock']))
