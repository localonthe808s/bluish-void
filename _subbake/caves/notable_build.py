"""Hand-curated notable caves -> under/caves_notable_v1.json  (built 2026-11-07).

Figures: lengths/depths from the English Wikipedia tables "List of longest caves" and
"List of deepest caves" (revisions read 2026-11-07; those tables cite the Quintana Roo
Speleological Survey, NPS, CINDAQ and expedition reports), cross-checked against each
cave's own article / NPS / operator page.  Bob Gulden's caverbob.com lists are offline
(domain parked after his death), so they could not be used directly.
Coordinates: Wikipedia/Wikidata article coordinates (entrance or main entrance area);
entries with approx=True are only area-level (entrances withheld or not published).
Text: plain English, American spelling, no emoji.
Run: python3 -I notable_build.py OUT.json
"""
import json, sys
R = []
def c(n, lat, lon, where, kind, fact, src, len_km=None, depth_m=None, asof=None, approx=False):
    d = {"n": n, "lat": round(lat, 4), "lon": round(lon, 4), "where": where, "kind": kind}
    if len_km is not None: d["len_km"] = len_km
    if depth_m is not None: d["depth_m"] = depth_m
    if asof: d["asof"] = asof
    d["fact"] = fact; d["src"] = src
    if approx: d["approx"] = True
    R.append(d)
W_L = "Wikipedia, List of longest caves"
W_D = "Wikipedia, List of deepest caves"
# ---- longest ---------------------------------------------------------------
c("Mammoth Cave", 37.18758, -86.10357, "Kentucky, USA", "longest",
  "The longest known cave system on Earth, with more than 426 miles of mapped passages under the Green River valley.",
  "NPS Mammoth Cave; " + W_L, len_km=685.6, asof="2022")
c("Sistema Ox Bel Ha", 20.16028, -87.4875, "Quintana Roo, Mexico", "longest",
  "The longest explored underwater cave in the world, a flooded maze reached through more than 160 cenotes near Tulum.",
  "CINDAQ 2025 report; " + W_L, len_km=541.7, asof="2026-02")
c("Shuanghedong", 28.24199, 107.27608, "Guizhou, China", "longest",
  "Asia's longest cave and the largest known dolomite cave system, still growing with every expedition.",
  "Grottes et karsts de Chine; " + W_L, len_km=481.5, asof="2026")
c("Sistema Sac Actun", 20.24656, -87.46411, "Quintana Roo, Mexico", "longest",
  "A mostly flooded cave system under the Yucatan jungle, joined with Dos Ojos in 2018; divers found Maya and Ice Age remains inside.",
  "QRSS 2025; " + W_L, len_km=387.1, asof="2025-01")
c("Jewel Cave", 43.72944, -103.82944, "South Dakota, USA", "longest",
  "The second-longest cave in the US, a maze lined with calcite crystals in the Black Hills.",
  "NPS Jewel Cave", len_km=354.59, asof="2025-07")
c("Wind Cave", 43.55635, -103.47865, "South Dakota, USA", "longest",
  "The first cave made a national park (1903); it holds about 95 percent of the world's known boxwork formations.",
  "NPS Wind Cave", len_km=270.4, asof="2025")
c("Clearwater Cave", 4.065, 114.83139, "Sarawak, Malaysia", "longest",
  "A river cave inside Gunung Mulu, one of the largest interconnected cave systems by volume.",
  "Wikipedia, Clearwater Cave system", len_km=265.9, asof="2025-11")
c("Optymistychna Cave", 48.7425, 25.99361, "Ternopil Oblast, Ukraine", "longest",
  "The longest gypsum cave in the world and the longest cave of any kind in Europe.",
  W_L, len_km=264.5, asof="2025")
c("Lechuguilla Cave", 32.19056, -104.50306, "New Mexico, USA", "longest",
  "A pristine cave dissolved by sulfuric acid rising from oil fields below; closed to the public and entered only by researchers.",
  "NPS Carlsbad Caverns; " + W_L, len_km=244.8, depth_m=484, asof="2025")
c("Fisher Ridge Cave System", 37.19174, -85.98012, "Kentucky, USA", "longest",
  "Found in 1981 just east of Mammoth Cave; most of it lies under private land.",
  W_L, len_km=215.9, asof="2025")
c("Hölloch", 46.97664, 8.78839, "Muotathal, Switzerland", "longest",
  "Hell Hole, a limestone cave that floods fast after heavy rain; over 1,000 m deep as well as long.",
  W_L, len_km=213.2, depth_m=1033, asof="2025")
c("Toca da Boa Vista", -10.1625, -40.85972, "Bahia, Brazil", "longest",
  "The longest cave in South America, a hot, humid maze in 600-million-year-old dolomite.",
  W_L, len_km=114, asof="2025")
# ---- deepest ---------------------------------------------------------------
c("Krubera (Voronya) Cave", 43.40972, 40.36222, "Arabika Massif, Abkhazia, Georgia", "deepest",
  "The first cave explored below 2,000 m (2004); surveys put its bottom at about 2,200 m below the entrance.",
  W_D + " (as of 2025); Wikipedia, Krubera Cave", depth_m=2224, len_km=23.0, asof="2025")
c("Veryovkina Cave", 43.41556, 40.35639, "Arabika Massif, Abkhazia, Georgia", "deepest",
  "One of only two caves known to go deeper than 2,000 m; its entrance sits at 2,285 m in the Gagra Range.",
  "Wikipedia, Veryovkina Cave (Perovo Speleo Club)", depth_m=2209, len_km=17.5, asof="2025")
c("Sarma Cave", 43.394, 40.3725, "Arabika Massif, Abkhazia, Georgia", "deepest",
  "The third-deepest known cave, found in 1990 by cavers from Irkutsk; bottomed at 1,830 m in 2012.",
  W_D, depth_m=1830, len_km=19.2, asof="2025")
c("Snezhnaya (Tovliani) Cave", 43.2647, 40.7183, "Bzyb Massif, Abkhazia, Georgia", "deepest",
  "Its name means snowy in Russian (Tovliani in Georgian); one of the deepest caves in the Caucasus.",
  W_D, depth_m=1760, len_km=40.8, asof="2025", approx=True)
c("Lamprechtsofen", 47.52611, 12.73917, "Salzburg, Austria", "deepest",
  "Was the deepest known cave in the world until Krubera passed it in the early 2000s.",
  W_D, depth_m=1727, len_km=61.0, asof="2025")
c("Sistema Huautla", 18.12121, -96.80001, "Oaxaca, Mexico", "deepest",
  "The deepest cave in the Western Hemisphere, with 30 entrances in the Sierra Mazateca.",
  "Wikipedia, Sistema Huautla", depth_m=1560, len_km=100.2, asof="2024-05")
c("Gouffre Berger", 45.21917, 5.60444, "Vercors, France", "deepest",
  "The first cave explored past 1,000 m deep (1956); the world's deepest known cave from 1953 to 1963.",
  W_D + "; Wikipedia, Gouffre Berger", depth_m=1258, len_km=45.0, asof="2025")
c("Hranice Abyss", 49.532, 17.75078, "Moravia, Czech Republic", "deepest",
  "The deepest known flooded pit cave: 519.5 m confirmed, 450 m of it underwater, likely carved by rising hot acidic water.",
  "Wikipedia, Hranice Abyss", depth_m=519.5)
# ---- biggest chambers / passages --------------------------------------------
c("Son Doong", 17.45694, 106.2875, "Quang Tri, Vietnam", "chamber",
  "The largest known cave passage by volume, with its own jungle and clouds under two collapsed skylights.",
  "Wikipedia, Hang Son Doong")
c("Sarawak Chamber", 4.07189, 114.87682, "Gunung Mulu, Malaysia", "chamber",
  "The largest known cave chamber by floor area, inside Gua Nasib Bagus (Good Luck Cave).",
  "Wikipedia, Sarawak Chamber")
c("Miao Room", 25.4, 105.9, "Guizhou, China", "chamber",
  "The largest known cave chamber by volume: 852 m long and about 10.78 million cubic meters, laser-scanned in 2013.",
  "Wikipedia, Miao Room", approx=True)
c("Deer Cave", 4.1319, 114.9189, "Gunung Mulu, Malaysia", "chamber",
  "One of the world's largest cave passages; millions of bats stream out of it at dusk.",
  "Wikipedia, Deer Cave")
c("Majlis al Jinn", 22.88064, 59.10521, "Selma Plateau, Oman", "chamber",
  "One of the largest cave chambers on Earth, entered only by rappelling through holes in its roof.",
  "Wikipedia, Majlis al Jinn")
c("Cave of the Crystals", 27.85083, -105.49639, "Naica, Chihuahua, Mexico", "chamber",
  "A chamber 300 m down in a mine holding selenite crystals up to 11.4 m long, in air as hot as 136 F.",
  "Wikipedia, Cave of the Crystals")
# ---- show caves ------------------------------------------------------------
c("Carlsbad Caverns", 32.17528, -104.44389, "New Mexico, USA", "show",
  "Its Big Room is almost 4,000 ft long and 255 ft high; Brazilian free-tailed bats fly out at dusk in summer.",
  "NPS Carlsbad Caverns; Wikipedia")
c("Luray Caverns", 38.6643, -78.48381, "Virginia, USA", "show",
  "Home of the Great Stalacpipe Organ, which taps stalactites to play music; shown to visitors since its discovery in 1878.",
  "Wikipedia, Luray Caverns")
c("Kartchner Caverns", 31.83557, -110.34368, "Arizona, USA", "show",
  "A living cave found in 1974 and kept secret by its discoverers until it could be protected as a state park.",
  "Arizona State Parks; Wikipedia")
c("Waitomo Glowworm Cave", -38.2608, 175.1036, "North Island, New Zealand", "show",
  "Visitors drift by boat under thousands of glowworms, a species found only in New Zealand.",
  "Wikipedia, Waitomo Glowworm Cave")
c("Postojna Cave", 45.78267, 14.20367, "Slovenia", "show",
  "A 24 km cave carved by the Pivka River, toured by underground train; home of the blind cave salamander, the olm.",
  "Wikipedia, Postojna Cave", len_km=24.34)
c("Škocjan Caves", 45.66207, 13.98448, "Slovenia", "show",
  "The Reka River runs through one of the largest known underground canyons; a UNESCO World Heritage Site since 1986.",
  "UNESCO; Wikipedia, Škocjan Caves")
c("Reed Flute Cave", 25.30444, 110.27556, "Guilin, China", "show",
  "More than 70 ink inscriptions line its walls, the oldest written in 792 AD.",
  "Wikipedia, Reed Flute Cave")
c("Jenolan Caves", -33.82056, 150.02139, "New South Wales, Australia", "show",
  "Clay dating suggests these are the oldest known open caves in the world, about 340 million years old.",
  "Wikipedia, Jenolan Caves")
c("Cango Caves", -33.39278, 22.21472, "Western Cape, South Africa", "show",
  "More than 4 km of chambers in Precambrian limestone; about a quarter is open on guided tours.",
  "Wikipedia, Cango Caves")
# ---- lava tubes ------------------------------------------------------------
c("Kazumura Cave", 19.52, -155.03, "Hawaii Island, USA", "lava",
  "The longest and deepest lava tube known, formed about 500 years ago in a flow from Kilauea Iki.",
  "Wikipedia, Kazumura Cave", len_km=65.5, depth_m=1102, approx=True)
c("Ape Cave", 46.1081, -122.212, "Mount St. Helens, Washington, USA", "lava",
  "A lava tube about 2.5 miles long, formed roughly 2,000 years ago and open for self-guided visits.",
  "USDA Forest Service; Wikidata", len_km=4.0)
c("Manjanggul", 33.5282, 126.7701, "Jeju Island, South Korea", "lava",
  "A lava tube up to 30 m high with a 7.6 m lava column, part of a UNESCO World Heritage Site.",
  "Wikipedia, Manjanggul", len_km=8.9)
c("Cueva del Viento", 28.34667, -16.72222, "Tenerife, Spain", "lava",
  "Europe's largest lava tube system, three levels deep, with fossils of extinct giant lizards and rats.",
  "Wikipedia, Cueva del Viento", len_km=17)
c("Cueva de los Verdes", 29.16111, -13.43889, "Lanzarote, Spain", "lava",
  "Part of a lava tube from La Corona volcano that runs out under the sea; it has a concert hall inside.",
  "Wikipedia, Cueva de los Verdes")
# ---- ice -------------------------------------------------------------------
c("Eisriesenwelt", 47.50294, 13.19025, "Werfen, Austria", "ice",
  "The largest ice cave in the world, more than 42 km long; ice forms where cold winter air sinks into the entrance.",
  "Wikipedia, Eisriesenwelt", len_km=42)
c("Dobšiná Ice Cave", 48.87194, 20.29472, "Slovak Paradise, Slovakia", "ice",
  "A cave filled with layered ice, part of a UNESCO World Heritage Site and one of the lowest ice caves in the world.",
  "Wikipedia, Dobšiná Ice Cave")
c("Scărișoara Cave", 46.48972, 22.80972, "Apuseni Mountains, Romania", "ice",
  "Holds one of the largest underground ice blocks in the world, thousands of years old.",
  "Wikipedia, Scărișoara Cave")
# ---- sea caves -------------------------------------------------------------
c("Fingal's Cave", 56.43389, -6.33611, "Staffa, Scotland", "sea",
  "A sea cave built of six-sided basalt columns, famous for its echoes and Mendelssohn's Hebrides overture.",
  "National Trust for Scotland; Wikipedia")
c("Blue Grotto", 40.561, 14.20569, "Capri, Italy", "sea",
  "Sunlight passes through an underwater opening and lights the water from below a vivid blue.",
  "Wikipedia, Blue Grotto (Capri)")
c("Sea Lion Caves", 44.1224, -124.1276, "Oregon coast, USA", "sea",
  "A system of sea caves open to the Pacific, where Steller sea lions gather.",
  "Wikipedia, Sea Lion Caves")
c("Painted Cave", 34.07082, -119.85628, "Santa Cruz Island, California, USA", "sea",
  "One of the largest sea caves in the world, nearly a quarter mile long, named for its colorful rock and lichens.",
  "NPS Channel Islands; OSM entrance point")
# ---- cave art --------------------------------------------------------------
c("Lascaux", 45.05361, 1.17, "Dordogne, France", "art",
  "Over 600 wall paintings of animals made roughly 17,000 to 22,000 years ago; found by teenagers in 1940.",
  "Wikipedia, Lascaux; UNESCO")
c("Chauvet Cave", 44.3875, 4.41417, "Ardèche, France", "art",
  "Some of the oldest and best-preserved figurative paintings known, sealed by a rockfall until 1994.",
  "Wikipedia, Chauvet Cave; UNESCO")
c("Altamira", 43.3825, -4.12028, "Cantabria, Spain", "art",
  "The first cave paintings put forward as Ice Age art (1880); the earliest were made about 36,000 years ago.",
  "Wikipedia, Cave of Altamira")
c("Leang Tedongnge", -4.9401, 119.6723, "Sulawesi, Indonesia", "art",
  "A painted Sulawesi warty pig here is at least 45,500 years old; a nearby cave holds a scene dated to 51,200 years.",
  "Brumm et al. 2021, Science Advances; Oktaviana et al. 2024, Nature")
c("Cosquer Cave", 43.20278, 5.44917, "Marseille, France", "art",
  "Its painted chambers are reached only through an entrance 37 m underwater, drowned by rising seas since the Ice Age.",
  "Wikipedia, Cosquer Cave")
c("Cueva de las Manos", -47.15583, -70.65722, "Santa Cruz, Argentina", "art",
  "Hundreds of stenciled hands sprayed onto the rock in waves from about 7300 BC to AD 700.",
  "Wikipedia, Cueva de las Manos; UNESCO")
# ---- near New York City ----------------------------------------------------
c("Howe Caverns", 42.69654, -74.39861, "Schoharie County, New York", "near",
  "New York's best-known show cave, found by farmer Lester Howe in 1842, with a boat ride on an underground lake.",
  "Wikipedia, Howe Caverns")
c("Secret Caverns", 42.70954, -74.39197, "Schoharie County, New York", "near",
  "A small show cave 1.4 miles from Howe Caverns, ending at a 100 ft underground waterfall.",
  "Wikipedia, Secret Caverns")
c("Natural Stone Bridge and Caves", 43.74752, -73.85233, "Pottersville, New York", "near",
  "Eleven marble caves along Trout Brook in the Adirondacks, with a stone bridge carved by the stream.",
  "Wikipedia, Natural Stone Bridge and Caves")
c("Sam's Point Ice Caves", 41.66926, -74.35521, "Shawangunk Ridge, New York", "near",
  "Fault crevices in the Shawangunk Ridge where ice and snow can linger into summer.",
  "NY State Parks; Wikipedia, Sam's Point Preserve", approx=True)
c("Lost River Caverns", 40.58083, -75.33083, "Hellertown, Pennsylvania", "near",
  "Five limestone chambers found by quarry workers in 1883, with a stream whose source has never been traced.",
  "Wikipedia, Lost River Caverns")
c("Crystal Cave", 40.5257, -75.8426, "Kutztown, Pennsylvania", "near",
  "Found in 1871, it was the first show cave to open in Pennsylvania.",
  "Wikipedia, Crystal Cave (Pennsylvania)")
c("Indian Echo Caverns", 40.2529, -76.7168, "Hummelstown, Pennsylvania", "near",
  "A limestone show cave near Hershey, described in writing as early as the 1700s.",
  "Wikipedia, Indian Echo Caverns")
c("Penn's Cave", 40.88278, -77.61, "Centre County, Pennsylvania", "near",
  "A water-filled limestone cave toured entirely by boat.",
  "Penn's Cave; Wikipedia")
c("Lost River Gorge and Boulder Caves", 44.03778, -71.78389, "Kinsman Notch, New Hampshire", "near",
  "Caves among giant granite boulders in a glacier-carved gorge, not dissolved rock.",
  "Wikipedia, Lost River Reservation")
c("Polar Caves", 43.78083, -71.78222, "Rumney, New Hampshire", "near",
  "Nine talus caves among granite boulders left by the ice age; snow can linger in the deepest into summer.",
  "Wikipedia, Polar Caves Park")
json.dump(R, open(sys.argv[1], "w"), ensure_ascii=False, separators=(",", ":"))
print(len(R), "caves")
