# Ghost rivers, traced off the survey

`bathy/ghost_streams.json` (93 courses, 39 km) and `bathy/ghost_wetground.json`
(47 polygons, 6.9 km²) are Manhattan's buried water, lifted off the map that
recorded it rather than drawn from memory.

**Source.** Egbert Viele's *Sanitary & Topographical Map of the City and Island
of New York*, 1865 — public domain, NYPL scan, georectified by Map Warper as
map 36301. Fetched once at z16 (1,104 tiles, ~1.9 m/px) into a 6144×11776
mosaic; nothing is fetched at runtime and no Map Warper tile is served to
anyone. The mosaic is a build input, not a layer.

**How the geometry was derived.**

1. *Wet ink by hue.* Viele washes dry land a yellow-green (hue ≈ 75°) and wet
   ground — marsh, meadow, watercourse — a true green-to-teal. Hue 95–180° at
   S > 0.12 separates them; luminance alone does not, because the uptown marsh
   is dark and the Village corridors are pale. Opened with a 3 px disk, which
   erases block outlines, lettering and hill hachure while a real corridor
   (15–25 px) survives.
2. *1865 shoreline from the map itself.* G ≥ R is the surveyed land, filled and
   eroded ~45 m to shed the blue shoreline stroke. A modern borough polygon is
   useless here — it carries a century of landfill, so the whole 1865 coast
   falls inside it and the coastline comes back as a "stream".
3. *Clipped to Manhattan*, the one island the sheet covers end to end.
4. *Skeletonised* to centre-lines, broken at junctions, then re-stitched where ends
   meet and keep the same heading. **Breaking at the junctions is what let each branch
   be walked separately, and it also punched a hole at every confluence** — a tributary
   stopped short of the trunk it joined, so the network did not connect like a river.
   Each junction's centroid is recorded before it is cut out, and every branch endpoint
   within 7 px of one is snapped onto it; several branches landing on the same centroid
   is exactly what makes them meet. 513 of 618 endpoints snap.
5. *Smoothed, not straightened.* Douglas-Peucker is run at ~4 m, not the 13 m it
   started at: a skeleton through a smooth corridor is nearly straight, and a coarse
   tolerance collapses a whole reach to one chord, which is what made the first
   courses look like crudely pasted straight lines. Two rounds of Chaikin
   corner-cutting follow, endpoints pinned, and the renderer lays the path as
   quadratics through vertex midpoints. Courses average ~42 points instead of a
   handful.
6. *Named* by nearest match to the old hand-traced draft (320 m tolerance).
   All 12 names matched a real course; 37 of 93 carry one, the rest are
   genuine unnamed watercourses.

**What this replaced.** The previous `ghost_streams.json` was 20 hand-drawn
LineStrings. Measured against the survey, half were far off: Old Wreck Brook by
a median 2.2 km, Minetta Brook by 0.8–1.4 km, the Canal Street canal by 1.2 km.
Sunfish Pond's outlet (62 m), Great Kill (79 m) and Montayne's Rivulet (43 m)
were close. The old file is still at the repo root, untracked.

**A route that did not work.** USGS 3DEP LiDAR with sink-fill and D8 flow
accumulation finds modern drainage, not buried streams: at a usable threshold it
returned 25 courses that mostly follow graded avenue troughs, and it agreed with
nothing downtown, where the Village was regraded past any terrain signal. The
survey is the only honest source.

**Rebuild:** the scripts are one-offs in the session scratchpad
(`viele_wet2.py` → `viele_build.py`). Re-derive from the mosaic if the rules
above need retuning; the mosaic itself takes ~4 minutes to refetch.

---

# Brooklyn and Queens

Added 2026-08-29. The layers now hold three boroughs: 213 courses over 105 km and
68.5 km² of wet ground. Each feature carries `boro` and `src`, because the two
halves come from different surveys and are not equally good.

**Why not the same source.** Viele's sheet stops at Manhattan. Map Warper layer
1631, the "Topographical map of the counties of Kings and Queens", turned out to
be Walling's 1859 *county atlas* — property lines and township colour washes, with
marsh drawn as a monochrome engraved texture (line hatch and grass tufts) rather
than a colour wash. Nothing to key a hue on, and in built Brooklyn the creeks are
not drawn at all. It was rejected.

**What was used instead: USGS 15-minute quadrangles, 1897.** Public domain, on
the public `prd-tnm` S3 bucket, and already georeferenced:

    StagedProducts/Maps/HistoricalTopo/GeoTIFF/NY/NY_<quad>_<id>_<year>_62500_geo.tif

Four sheets tile the two boroughs — Brooklyn, Harlem, Hempstead and Oyster Bay,
all 1897/98. USGS printed water and marsh in **cyan-blue** on these, so
`B−R ≥ 26` separates it from everything else in one step.

**Georeferencing.** The GeoTIFFs are American polyconic on Clarke 1866 (NAD27)
with `ProjectedCSTypeGeoKey = User_Defined`, so no library will read them for you —
but every parameter is in the geokeys. `polyconic.py` (scratchpad) implements the
forward projection from Snyder, inverts it by Newton, and applies a Molodensky
NAD27→WGS84 shift. Verified by drawing the modern borough outlines onto the sheet:
they land exactly, and the gap at Jamaica Bay and Coney Island is real landfill.

**Three clips, all necessary:**
1. **Neatline.** Every sheet has a printed collar, and a *neighbour's* collar can
   sit on top of real ground — the Harlem sheet's archive stamp lands in Queens and
   came through as a watercourse shaped like the words "Topographic Division".
   Round each sheet's extent inward to the 15′ graticule; the four bodies tile
   exactly with no overlap.
2. **Today's borough land** (`nyc_boroughs.json`, which is land only — Jamaica Bay
   and the East River fall outside it). What is inside it *and* was water in 1897
   is water the city has since covered.
3. **Today's water and wetland**, from one Overpass query (`natural=water`,
   `wetland`, `coastline`). Without this the layer claims Jamaica Bay's surviving
   marsh islands as ghosts. Checked against known points afterwards: Rulers Bar and
   Big Egg (still marsh) out, Jamaica Bay open water out, Prospect Park out; JFK,
   Flushing Meadows and Starrett City in.

A centreline through a mile-wide marsh is not a stream, so the skeleton is kept
only where the distance transform says the wet ground was narrow enough to have
been a channel (< ~125 m across). Broad marsh stays a polygon.

**Known limits.**
- **1897 is late for western Brooklyn.** Gowanus, Wallabout, Bushwick and Sunswick
  creeks were already canalized or filled by then, so they are absent — the name
  matcher found nothing within 3 km of Gowanus or Wallabout. Only 9 of 120
  Kings/Queens courses carry a name, against 37 of 93 in Manhattan.
- **Bay Ridge, west of −74.00, is uncovered** — no 1890s 62,500 quad for that block
  exists in the bucket under any name tried.
- Names here were attached **by position** from a small table in `name_kq.py`, not
  read off the sheet.

---

# Accuracy, checked

Run 2026-08-29 (`audit_ghosts.py`, `crosscheck.py` in the scratchpad). Four
independent tests, because "it looks right" is not a measurement.

**1 · Two surveys, independently.** The USGS 1897 Harlem sheet also covers upper
Manhattan, so the same signal can be pulled from a second survey with a different
projection and a different extraction rule and compared with the Viele trace.
Where both show water the median offset is **27 m** (90th percentile 88 m) — at
1:62,500 the printed line is about 30 m wide, so that is agreement, and it
validates the hue extraction and the polyconic georeferencing at once. Only 18% of
Viele courses appear on the 1897 sheet at all: between 1865 and 1897 upper
Manhattan was built and sewered, so absence there is not evidence of error.

**2 · Landmarks.** 19 places whose modern identity records the buried water — a
street named for it, a park built on it, a basin that is all that is left.
**15 of 19** sit on a course or inside the wet ground. The four that do not:

| place | result |
|---|---|
| Paerdegat Basin | Correct. The basin is still water, so it is subtracted — not a ghost. |
| Alley Pond | Correct, same reason. |
| Great Kill mouth, W 42nd | 535 m. The course exists inland; the mouth is trimmed by the ~45 m shoreline erosion. |
| Saw Kill, E 74th | 943 m. A real gap — see below. |

**3 · Controls.** Eight points of dry upland that were never wet — Washington
Heights ridge, Prospect Park hilltop, Forest Hills ridge, Bay Ridge bluff,
Carroll Gardens, and others. **0 of 8** flagged. Nearest course to any of them is
135 m; the median is over 1 km.

**4 · Structure.** 213 courses, 157 polygons, no faults: no degenerate geometry,
no unclosed rings, no duplicates, nothing outside the NYC bounding box, every
feature carrying its source.

## The one real gap this found

Below Third Avenue the Saw Kill is drawn on Viele as a **bare ink line with no
marsh wash** — the extraction keys on the wash, and a 3 px opening erases a line
that thin. So the layer holds water Viele *washed* as marsh or meadow, plus its
blue channels; it does not hold reaches drawn only as a line through upland. A
narrow-line detector was tried and rejected: on that sheet the line is desaturated
and broken up by hill hachure, and the version that caught it also caught street
ruling. Better a stated gap than a layer with invented streams in it.

## Names were rebuilt

The Manhattan names had been inherited from the old hand traces by proximity — and
since those traces were up to 2.2 km out, some names landed on the wrong course:
the audit found one labelled "Minetta Brook headwaters" sitting near West 42nd.
Every Manhattan name was cleared and re-attached from an explicit table of
documented positions (`rename_manhattan.py`), matching within 350 m; anchors now
land 32–309 m from their reference point. Named courses drop from 46 to **20**,
which is the honest count: a name now means a documented position, not a guess.

---

# What you are looking at

**One water family, two states.** Every piece of ground that ever held water — the
marsh, the buried courses, and the water still standing — is the same light blue
field, so the city's whole water story reads as one shape rather than as a historic
layer sitting on a modern map. Inside that field:

- **Light blue fill** (`#9dc4ea`) — ground that was or is water.
- **Solid dark blue** (`#17457F`) — the water that is *still there*, drawn in **two
  passes**. A creek is narrow, so a soft edge is most of its width and it melts into the
  pale field, which is the point. A settling basin at the Newtown Creek plant is small but
  *compact*, and the same feather on a sixty-metre rectangle just looks out of focus. The
  split is on each feature's own `bbox`: `maxDataZoom` is pinned at 14, so tile units map
  to a fixed ground size and the minor dimension is a stable measure of narrowness. Under
  60 units (~35 m) the water is feathered; over it, crisp.

  An earlier version laid a wide pale halo underneath first, to guarantee something for
  the water to fade into. It ringed **every** body in white, including the big ones, and
  is gone. Where no historic marsh sits behind a creek it now fades into whatever is
  there, which is a two-pixel rim and much better than a glow. A later version feathered
  *all* water at once, which is what made the treatment plant look out of focus.
- **A blue band that bleeds** (`#3B71CA`) — a buried watercourse. Stroked into a mask and
  laid down three times at falling blur and rising opacity, the same build the flood zones
  use, so it fades into the pale field like a heat map instead of sitting on top of it as
  a drawn line. That is the honest reading too: a buried stream is a best estimate of
  where the water ran, and a crisp stroke claims more than the survey supports. Mask width
  runs 2.2–4.2 px with the length of the course, so a trunk carries more than a stub.
- **Radioactive lime, glowing** — a modelled flood zone. Deliberately outside the water
  family: it is a forecast, not water, and on the orange nothing else on the map comes
  near it. The glow is real rather than an effect — a wide faint pass well beyond the
  shape, with the intense colour held to the core, so the edge falls off like light.

Both course strokes are **solid**. Dashing them put a round cap on either end of every
dash, so each course came out as a string of beads. The wash needs an edge for the same
reason — without one it reads as a smudge.

A course does not always run the length of its marsh: the centreline is only kept
where the wet ground was narrow enough to have been a channel, so a broad marsh is
drawn as an area with no line through it, and a neck between two marshes gets a line.
That is deliberate, not a gap.

---

# Flood-prone zones

Added 2026-08-29. `bathy/flood_stormwater.json` — **NYC DEP Stormwater Flood Map**,
moderate scenario at today's sea level, from the city's public ArcGIS:

    services5.arcgis.com/GfwWNkhOj9bNBqoJ/.../DEP_Stormwater___Moderate_with_Current_Sea_Level_Rise/FeatureServer/14

This is *pluvial* flooding — rain standing in the street, the kind that fills
basements a mile from any FEMA zone. FEMA's NFHL maps coastal and riverine flooding
and would tell the wrong story here. Two classes: nuisance (4 in–1 ft) and deep and
contiguous (≥1 ft).

**It cannot be fetched live.** It is a raster-derived polygonization: the whole city
comes back as 13 MB across 27,600 rings even generalised server-side, and ArcGIS does
not clip to the query envelope. Baked once instead — rings under 200 m² dropped, which
sheds three quarters of them and keeps **91% of the flooded area**, then simplified to 9 m. 7,072 polygons, 1.9 MB, 10.5 km². For the live site this should become raster
tiles on R2 rather than GeoJSON.

**Colour.** Red outlines the zones; the courses went back to plain blue. Bright red
(`#E5342A`) is nearly invisible against the lab's orange borough mask — it needed a
deep crimson (`#A5101A`) with a darkening fill to separate from the land under it.

## Does flooding actually follow the buried water?

Measured, not assumed (`overlap.py`, `overlap2.py`): both layers rasterised to a 20 m
grid over the three boroughs, comparing the share of modelled flooding that falls on
ghost ground against the share of *all* land that is ghost ground.

| | ghost ground | deep flooding on it | enrichment |
|---|---|---|---|
| Manhattan · marsh | 12.8% | 24.8% | **1.93×** |
| Manhattan · course within 60 m | 12.5% | 11.0% | 0.88× |
| Brooklyn/Queens · marsh | 13.8% | 9.7% | **0.71×** |
| Brooklyn/Queens · course within 60 m | 2.6% | 3.8% | 1.44× |

**Two findings, one of them against the thesis.**

In Manhattan deep flooding is **twice as likely** on the old marsh as on the island at
large. But it is the *marsh* that predicts it, not the stream line — a 60 m corridor
around the courses shows nothing (0.88×). The valley floor is the signal; the thread
down the middle of it is not.

In Brooklyn and Queens the relationship **inverts**: modelled flooding is *less* likely
on the old marsh than elsewhere (0.71×). That is not a defect in either layer — those
marshes were filled, raised and drained on purpose. JFK, the Flushing Meadows,
Canarsie and Starrett City were engineered not to flood, and by this model they do not.

So the honest citywide number is **no enrichment at all** (0.96× deep, 0.94× nuisance):
the Manhattan signal and the outer-borough inversion cancel. Any "the city floods where
the rivers were" headline is only defensible for Manhattan, and only about the marsh.

---

# The subway

`bathy/subway_lines.json` (29 routes, 806 km) and `bathy/subway_stops.json` (496
stations), built from the **MTA's own GTFS feed** — `rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip`,
public and keyless. The published track alignment, not a redrawing of it.

- One shape per **route**, not per trip: a route has dozens of short-turn variants, so
  the longest shape wins. The two directions run the same track, so they collapse to one
  line — drawing both just doubles every stroke.
- Stops are **complexes**, not parent stations. GTFS keeps the IRT, BMT and IND halves
  of Times Square as three separate parent stations — labelling those directly printed
  "Times Sq-42 St" three times over. `transfers.txt` is what says they are one place, so
  the parents are union-found through it: 496 parent stations collapse to **444
  complexes**, and Times Square comes out once carrying 1 2 3 7 A C E N Q R W S. A
  complex takes the name of its **busiest** member; "longest name" made Times Square
  come out as 42 St-Port Authority Bus Terminal.
- Routes serving each station are walked out of `stop_times` → `trips` → `routes`.
  Shuttles all present as **S**, express variants take their line's bullet.
- Vertices thinned to 25 m and given one round of Chaikin, same as the courses.

**Drawn in the MTA's own route colours**, straight from the GTFS `route_color`; the no-purple
rule does not apply, since these are data-driven. A white casing under every line keeps
them apart where four share an avenue.

Station labels are a **vertical stack**: route bullets, then the cross street in bold,
then the place under it. MTA names carry both halves in one string joined by a hyphen and
the order is not consistent — "34 St-Penn Station" but "Times Sq-42 St" — so `splitStation`
pulls out whichever part reads as a street, and the street always lands on the same line.
A hyphen **between digits** is part of a name rather than a separator: splitting
"47-50 Sts-Rockefeller Ctr" naively yields "47". Bullets stack **four to a row**, and a colour group never
splits across rows — the A C E stay together and so do B D F M. They are gathered by
colour **globally**, not by adjacency: MTA order runs A B C D E F G, so the blues and
oranges interleave and adjacent grouping would give seven groups of one. Groups are then
packed in order, a row taking a whole group or starting a new one. Times Square comes out
1237 / ACE / NQRW / S; Herald Square BDFM / NQRW; W 4 St ACE / BDFM. Two zoom gates: the **dots** appear below 22 m per pixel and the **names** below 9 m per
pixel. At city framing 444 white dots bead along every line and read as the network
itself, drowning the lines they are meant to sit on — so out there the coloured lines
carry it alone. The live pane gates its station layer the same way at zoom 13, with the
handler stored on the map so a rebuild replaces it rather than stacking another.

The whole label is **centre-aligned on the bullet block**: each bullet row is centred, so
a two-bullet row sits under a four, and the street and place are centred under both.
Labels are placed with a rectangle-overlap test; one that collides is dropped rather than
stacked.

## What the overlay is worth

Measured on the same 20 m grid as the flood work, for the 405 stations in the three
boroughs:

| | stations | land baseline | enrichment |
|---|---|---|---|
| within 100 m of buried water | 80 (20%) | 25% | 0.78× |
| inside a deep-flood polygon | 7 (2%) | 0.9% | **1.97×** |

Stations are *not* built on the buried streams — slightly less often than chance, which
makes sense, since the lines follow the avenues along the ridges rather than the valley
floors. But a station is **twice as likely as the ground around it to sit in a
deep-flooding polygon**. Seven of them do. That is the pairing worth showing, and it is
about today's topography rather than the old watercourses.

---

# One view, and it pans and zooms

The lab used to draw the same geography twice — an interactive Leaflet pane above the
static card — and the two diverged the moment you panned either, since the card always
rendered the fixed view box. The artwork only ever lived on the card, so the Leaflet pane
went; the card gained the interaction instead, and the lab no longer loads Leaflet at all.

The card keeps its state in **web mercator** — left edge, vertical centre, metres per
pixel — because that is what `Static` consumes: it reads zoom off the longitude span and
takes a centre latitude, so the vertical extent follows the canvas aspect rather than any
latitude pair. Wheel and double-click zoom **about the cursor**, drag pans, and there are
+/−/reset buttons.

A full repaint is a second or more, so during interaction the last finished bitmap is
transformed into place as a preview and the real render fires 260 ms after the pointer
goes quiet. Each render carries a token and abandons itself if a newer one has started,
which is what stops a slow pass from painting over a newer view.

The note below is kept because the Leaflet pane trap is real and will bite again if a
Leaflet map ever comes back.

Leaflet stacks by **pane, not by add order**, and the two kinds of layer here sit in
different ones: `protomapsL.leafletLayer` is a grid layer in `tilePane` (z 200) while
`L.geoJSON` draws into `overlayPane` (z 400). So the opaque borough mask covered the
parks-and-rivers pass no matter when it was added, and every park inside the city was
invisible — `bringToFront()` cannot help, because it only reorders within a pane.

Each band now has its own pane:

| pane | z | what |
|---|---|---|
| `tilePane` | 200 | the base map |
| `bvMask` | 350 | borough mask, neighbourhood lines |
| `bvParks` | 360 | parks and rivers, put back over the mask |
| `overlayPane` | 400 | ghost water, flood zones, subway |
| `bvLabels` | 480 | place names, which have to clear all of it |

**Never pass `pane: undefined`.** It does not mean "use the default" — it overrides
Leaflet's prototype default with undefined, `getPane()` then returns nothing, and the
layer dies on `appendChild`, taking the whole map down with it. Set the key only when
there is a pane to set.

---

# Park names

`bathy/park_labels.json` — 2,849 named greens from OSM (`leisure=park|garden|nature_reserve|common`,
`landuse=grass|meadow|forest|recreation_ground`, `natural=wood|scrub|grassland`), each carrying
a name, an anchor point and its bounding box.

**Central Park is deliberately not in the file.** At the zoom where its own name would fit,
the interesting labels are its parts, and OSM has them: Sheep Meadow, The Ramble, The Ravine,
The Dene, Cedar Hill, East and North Meadow, East Green, Great Hill, Conservatory Garden,
Hallett Nature Sanctuary, Arthur Ross Pinetum. A second Overpass query scoped to the park's
own box was needed to pick up the ones tagged as woods and grass rather than as parks.

**One park, one label.** A park can be many polygons spread over kilometres — Pelham Bay
Park is five — so same-name polygons are clustered transitively at 2.5 km and the cluster
is labelled once, at the anchor of its largest piece and with the union of their bounding
boxes as its extent. Deduping at 600 m, which is what this did first, printed PELHAM BAY
PARK five times across the same park.

**The anchor is not the centroid.** A centroid falls outside a bent park — Riverside Park's
would land in the Hudson. Each label point is the sampled interior point furthest from any
edge, a cheap pole of inaccessibility.

**Names stack on their own words, not at whatever width runs out.** One word a line while
the name is short; only past three tokens do the words pair up:

| | |
|---|---|
| Flushing Meadows-Corona Park | FLUSHING MEADOWS / CORONA PARK |
| Queens Botanical Garden | QUEENS / BOTANICAL / GARDEN |
| Kissena Corridor Park | KISSENA / CORRIDOR / PARK |
| The Ravine | THE RAVINE |

Two rules earn their keep. **A hyphen is a word break** — OSM stores "Flushing
Meadows-Corona Park", which as three tokens stacks FLUSHING / MEADOWS-CORONA / PARK; broken
at the hyphen it is four and pairs correctly. (A hyphen between digits is left alone.) And
**articles ride with their word**, so it is THE RAVINE, never THE over RAVINE. Set in caps
with a little letter-spacing, which reads as a park label and keeps them apart from the
station names.

**A name appears when it fits, not at a zoom number.** It is drawn only if the stacked block
sits inside 86% of the park's own projected box width and 74% of its height, with the park at
least 34 px across. So a short name on a small green appears earlier than a long one, which
is what "fits cleanly" actually means. Lines are centred on the anchor, and a label that
would overlap one already placed is dropped. At city framing exactly one label survives
citywide — Randalls Island Park.

The live pane still uses the basemap's own place labels; this is the card render only.

---

# Neighbourhood names

`bathy/hood_labels.json` — 340 names, 21 districts and 319 neighbourhoods, from OSM
`place=quarter` and `place=neighbourhood`, clipped to the five borough polygons (which
sheds Avenel, Sewaren and the rest of New Jersey).

**Not the NTAs**, which is what this was built on first and was wrong. The 2020
Neighborhood Tabulation Areas are NYC Planning's *statistical* geographies: they fuse
neighbourhoods into administrative units and label them accordingly — "Tribeca-Civic
Center", "Battery Park City-Lower Manhattan", "Carroll Gardens-Cobble Hill-Gowanus-Red
Hook". Nobody says any of those. OSM carries the vernacular names, so Tribeca, SoHo, NoHo,
Civic Center, Battery Park City, Two Bridges, Seaport and Alphabet City are each
themselves. The NTA polygons are still used, but only for the faint boundary lines.

**Two tiers, because they are not the same kind of thing.** Rank 1 is a district you can
read from a distance — Harlem, Midtown, Williamsburg, Flushing, Long Island City — and
appears below 55 m per pixel. Rank 2 is the fine grain and waits until 22. Most entries
are points, so there is usually no shape to fit inside; where one carries a boundary the
name still has to sit within it.

**Set in Qellia**, the site's display serif, at weight 500 — it is a single-weight face
and asking for a bold invites a synthesised one. It runs about a fifth narrower and much
lighter in stroke than the sans (measured: 124 px against Georgia's 173 for the same
string), so 9 px reads smaller here than 9 px elsewhere. No halo — the white edging turned
every name into a sticker.

The font is served from `_maplab/qellia.woff2`, **not the CDN**: a font is a CORS fetch and
`cdn.bluishvoid.com` only allows `bluishvoid.com`, so from localhost the face never
arrives and canvas quietly falls back to Georgia with no error. And canvas text does not
trigger a font load the way DOM text does, so the first paint waits on
`document.fonts.load` before drawing.

## One collision list for all three

Neighbourhood, park and station labels now share `LABELBOX`, filled in that priority
order, so a later label gives way to one already placed instead of printing through it.
Before this each kind kept its own list and only avoided its own kind.

---

# Green that is not park

`parkRulesFor` deliberately omits **`grass`**. In OSM that tag covers highway infill —
cloverleaf loops, median strips, the ribbons along the BQE — as much as it covers a lawn,
and it was painting whole interchanges green. Measured on a frame of the BQE/LIE knot in
Queens, `grass` was 1.44% of the frame, and probing the features showed the tiles carry
**nothing to tell the two apart**: a grass feature arrives with only `kind` and
`sort_rank` — no `kind_detail`, no `name`.

Nothing that matters was lost by dropping it. A park is `park`, a ball field is `pitch`, a
cemetery is `cemetery` (10% of that same frame, and correctly so — those are the Queens
cemeteries), and Central Park's meadows sit inside the park polygon, so Sheep Meadow and
Cedar Hill are still green and still labelled.

---

# Where the sewers empty

`bathy/cso_outfalls.json` — the **415 combined sewer overflow outfalls**, from NYC DEP's
*Citywide Outfalls* (`8rjn-kpsh` on NYC Open Data; 5,428 outfalls in all, of which CSO is
one type). About 60% of the city is on a combined system — one pipe for sewage and street
runoff — and when rain fills that pipe the mix discharges untreated at these points.

Where they go: East River 138, Hudson 53, Harlem River 41, Upper New York Bay 26, Kill Van
Kull 20, Buttermilk Channel 11, **Gowanus Canal 10**, **Newtown Creek 14** (with its tidal
tributaries). By catchment: Newtown Creek plant 82, Wards Island 75, North River 52, Bowery
Bay 43, Port Richmond 37, Red Hook 35, Hunts Point 34. **A quarter of them — 100 of 415 —
discharge into a former tidal creek, canal or kill** rather than open water.

**Colour took three tries**, and the reason is worth keeping. A *dark* brown over the dark
navy water is the same value as the water, so it mixed to mud. A *pale* brown is just a dim
orange, which is the land colour, so it went grey. What reads is a **saturated copper laid
nearly opaque** (`#B06A22`, core alpha .96): it separates from the navy by hue and from the
orange by depth, and because the core replaces the water rather than tinting it, the canal
reads as a different substance rather than as shading.

**Weighted by pipe size.** DEP records each outfall's dimensions, so a box or an egg is
reduced to the diameter of a circle with the same cross-section — flow follows area, not
the longest side. That parses for **413 of 415**, and they run from 10 inches to 294
(Alley Creek; then Flushing Creek at 184, Bergen Basin 177, English Kills 171). The seed
scales with it, so a trunk sewer stains further and harder than a 10-inch pipe instead of
every outfall contributing an identical blob.

**The pipe itself is drawn.** A stain with no mark on it is a smear you cannot attribute;
the outfall position is the one part of this layer that is measured rather than modelled,
so it gets a hard-edged dot, sized by the same diameter, once the framing is under 26 m
per pixel.

**Drawn as a stain, and the spread is geodesic.** Discharge does not go out in a circle —
it goes where the water goes. A round plume clipped to the water was the first attempt, and
it put stain on the far side of a headland while leaving the channel it should have run
down untouched. Now the stain is seeded at the outfall and grown one small step at a time
with the water mask reapplied *after every step*, so it can never leave the water: it creeps
along a creek and stops dead at a bank or a spit. Step size scales with zoom so the reach
stays about 750 m on the ground rather than a fixed number of pixels.

**And it decays.** The front is drawn **once** per step, not twice. Blurring conserves total
alpha while spreading it, so density falls as the plume grows — that is the whole mechanism.
An earlier version drew it twice each step so the front would survive the repeated clipping,
which *boosted* alpha instead of letting it decay and turned the result into a flat
"everywhere the water reaches" mask: a whole bay filled evenly, which is what it looked
like. Each step is added into an accumulator with `lighter`, so the near field carries the
sum of all twenty passes and the far field only the last few.

**What this does not model is tide or current.** There is no direction here beyond the shape
of the water itself. A downstream bias would look convincing and would be a guess dressed
as data.

The behaviour falls out of the geometry rather than being drawn: ten outfalls along
something as narrow as the Gowanus merge into one continuous brown channel, the Hutchinson
carries its stain down past Co-op City, and ten spread along the East River barely tint it.
Nothing is hand-picked — it is the 415 positions and the shape of the water.
`drawActiveWater` returns the mask it drew, which is what makes any of this possible.

**No volumes or frequencies are available.** The state's CSO dataset (`ephi-ffu6`) has a
`number_of_overflow_events` field, but for all 427 NYC outfalls it is blank — the entry
reads "Real-time waterbody advisory, visit website", because the city reports through a
live advisory instead. Annual discharge volumes exist only inside DEP's Waterbody/Watershed
Facility Plan PDFs. So the stain is uniform per outfall: it says *where*, never *how much*.

**A test that is not yet answerable.** Whether outfalls sit on the buried creeks — the
sewers were laid in the old valleys, so they should — came out at 0.61× against a coastline
baseline, i.e. *less* likely than average shoreline. That number is not trustworthy: only
42% of the outfalls fall in boroughs we have traced. The Bronx and Staten Island have no
ghost-river data at all, and 186 more could not be placed in any borough because an outfall
sits in the water, just outside the land polygon. The test is measuring coverage gaps, not
the city. It needs the Bronx and Staten Island traced, and shoreline-aware placement.

---

# The Bronx (added 2026-08-29)

The Bronx was never missing from the source — it was **thrown away at the clip**. Its whole
extent (−73.934…−73.765, 40.785…40.916) sits inside the Harlem 1897 neatline, a sheet
already downloaded for Manhattan and Queens; `build_kq.py` simply clipped to Brooklyn and
Queens polygons and discarded the rest. Adding `'Bronx'` to that list was the whole change,
plus one more Overpass fetch: the modern-water query stopped at 40.83 and the borough runs
to 40.92, so without extending it the northern Bronx would have kept water that is still
there.

The Harlem sheet went from 23 wet blobs to 70. Citywide the layer is now **457 courses over
232 km and 82.5 km² of wet ground**, up from 350 and 75.6.

**None of it is named.** Five Bronx reference points were tried — Tibbetts Brook, Mill
Brook, Westchester Creek, Pugsley's Creek, Rattlesnake Brook — and **all five failed to
match a course within the 650 m tolerance**. That is not the geometry being wrong; it means
either the coordinates are off, or those particular reaches were already culverted by 1897,
or they are still water today and were subtracted as such. The Bronx's 116 courses are
real and drawn, and every one of them is unnamed until that is chased down.

Staten Island is still untraced. Its quads were never downloaded.
