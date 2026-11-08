"""Karst / lava springs with a live USGS discharge gage -> under/springs_v1.json

Curated list, 2026-11-07. Every id was verified against the USGS Water Data OGC API
(latest-continuous, parameter 00060, reporting on 2026-11-07/08 UTC) and the
statistics/v0 observationNormals percentile endpoint (springs_probe.py).
Coordinates are the GAGE location from that API. USGS data: public domain.
Rejected on 2026-11-07: Silver Springs 02239500 (last value 2007; use the Silver River
gage 02239501), Spring Creek FL 02327031 (last 2020), Jackson Blue 02358795 (last 2006),
Wacissa 02326526 (last 2025-12), San Antonio Springs 08177818 (intermittent, last 2026-03),
Mammoth Spring AR 07069190 (value null, qualifier DISCONTINUED; 07069220 below it last 2016).
Not found as active discharge gages: Maramec Spring MO, Fall River CA, Davis Spring,
Wekiwa Springs FL, Alexander Springs FL.
Usage: python3 -I springs_bake.py <probe_dir> <out.json>
"""
import sys, json
probe, out = sys.argv[1:3]
F, L, D, DO = 'first magnitude', 'limestone', 'dolomite', 'lava'
S = [
 ('02239501','Silver Springs','FL',L,F,'Gaged on the Silver River just below the head spring, Silver Springs has carried glass-bottom boat tours since the 1870s.'),
 ('02313098','Rainbow Springs','FL',L,F,'A group of springs feeds the 5.7-mile Rainbow River, which joins the Withlacoochee at Dunnellon.'),
 ('02322700','Ichetucknee Springs','FL',L,F,'Nine major springs feed the six-mile Ichetucknee River, a tributary of the Santa Fe.'),
 ('02327022','Wakulla Springs','FL',L,F,'One of the largest and deepest freshwater springs on Earth; divers have mapped more than 30 miles of flooded cave behind it.'),
 ('02235500','Blue Spring (Volusia)','FL',L,F,'Winter refuge for hundreds of West Indian manatees that crowd into its 72-degree water.'),
 ('02236160','Silver Glen Springs','FL',L,F,'A spring in the Ocala National Forest whose short run empties into Lake George on the St. Johns River.'),
 ('02323566','Manatee Spring','FL',L,F,'Its quarter-mile run reaches the lower Suwannee River; the cave behind it is a well-known dive site.'),
 ('02323502','Fanning Springs','FL',L,None,'A spring on the lower Suwannee whose flow, once above 100 cubic feet per second, now usually runs below it.'),
 ('02319302','Madison Blue Spring','FL',L,F,'Rises beside the Withlacoochee River (north) at the entrance to an extensive underwater cave system.'),
 ('02310525','Weeki Wachee Springs','FL',L,F,'Mermaid shows have been performed in the spring since 1947.'),
 ('02310650','Chassahowitzka Springs','FL',L,F,'A cluster of springs feeding a short, mostly wild river that runs to the Gulf through a national wildlife refuge.'),
 ('02310678','Homosassa Springs','FL',L,F,'Main spring of the Homosassa group, inside Ellie Schiller Homosassa Springs Wildlife State Park.'),
 ('02321958','Santa Fe River Rise','FL',L,F,'Where the Santa Fe River, swallowed by a sinkhole at O\'Leno State Park, rises again about three miles away.'),
 ('02306000','Sulphur Springs (Tampa)','FL',L,None,'A Tampa spring fed through sinkholes in the Floridan aquifer, once a popular public swimming pool.'),
 ('07067500','Big Spring','MO',D,F,'One of the largest springs in the United States, pouring roughly 280 million gallons a day into the Current River.'),
 ('07071000','Greer Spring','MO',D,F,'Missouri\'s second-largest spring roughly doubles the flow of the Eleven Point River.'),
 ('06923500','Bennett Spring','MO',D,F,'A spring averaging about 100 million gallons a day feeds a state trout park and hatchery.'),
 ('07065495','Alley Spring (Jacks Fork)','MO',D,None,'River gage on the Jacks Fork at Alley Spring, beside the red 1894 mill; the flow includes the river above.'),
 ('07064440','Montauk Springs (Current River)','MO',D,None,'Springs in Montauk State Park form the head of the Current River; the gage includes the upper river.'),
 ('08169000','Comal Springs','TX',L,F,'The largest spring system in Texas rises from the Edwards Aquifer at New Braunfels; it stopped flowing in the 1956 drought.'),
 ('08170500','San Marcos Springs','TX',L,F,'Edwards Aquifer springs rising into Spring Lake; unlike Comal, they have never gone dry in recorded history.'),
 ('08155500','Barton Springs','TX',L,None,'Feeds Austin\'s Barton Springs Pool from the Edwards Aquifer and is the only home of the Barton Springs salamander.'),
 ('08427500','San Solomon Springs','TX',L,None,'A desert spring in West Texas that fills the huge spring-fed pool at Balmorhea State Park.'),
 ('08170990','Jacob\'s Well','TX',L,None,'An artesian karst spring in Cypress Creek fed by the Trinity Aquifer; it has stopped flowing in recent droughts.'),
 ('08168000','Hueco Springs','TX',L,None,'An Edwards Aquifer spring north of New Braunfels that goes dry in severe drought.'),
 ('08456310','Las Moras Springs','TX',L,None,'The spring that Fort Clark was built around at Brackettville, rising from Edwards-Trinity limestone.'),
 ('13095500','Box Canyon Springs','ID',DO,F,'Pours from the Snake River Plain basalt aquifer at the head of a box canyon, part of the Thousand Springs reach.'),
 ('13095175','Briggs Spring','ID',DO,None,'One of the Thousand Springs that issue from the basalt walls of the Snake River canyon near Buhl.'),
 ('13089500','Devils Washbowl Spring','ID',DO,None,'A spring discharging from Snake River Plain basalt in the canyon near Kimberly.'),
 ('14091500','Metolius River','OR',DO,None,'The Metolius rises nearly full-size from springs below Black Butte; this gage is well downstream and includes spring-fed tributaries.'),
 ('06111800','Big Spring Creek','MT',L,None,'Fed by Big Spring, which rises from the Madison Limestone and supplies Lewistown\'s water; the gage is downstream.'),
 ('03288110','Royal Spring','KY',L,None,'A karst spring in the Inner Bluegrass limestone at Georgetown, long the town\'s water supply.'),
]
res = []
for i, n, st, rock, mag, fact in S:
    d = json.load(open(f'{probe}/{i}.json'))
    g = d['latest']['features'][0]['geometry']['coordinates']
    o = {'id': 'USGS-' + i, 'n': n, 'st': st, 'lat': round(g[1], 4), 'lon': round(g[0], 4), 'rock': rock, 'fact': fact}
    if mag: o['mag'] = mag
    res.append(o)
json.dump(res, open(out, 'w'), separators=(',', ':'), ensure_ascii=False)
print(len(res))
