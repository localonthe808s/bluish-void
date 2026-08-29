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
- **Solid dark blue** (`#17457F`) with a **feathered edge** — the water that is *still
  there*. The basemap's own water shapes are rendered off-screen and used as a stencil;
  blurring the stencil and then filling *through* it with `source-in` keeps the colour
  flat and softens only the alpha, so the edge settles into the pale field instead of
  being cut out of it. Two passes: a wider pale halo, so there is always light blue for
  the water to fade into even where no historic marsh sits behind it, then the deep blue
  with a slight feather.
- **Blue line** (`#3B71CA`) — a buried watercourse. Weight runs 2.6–4.8 px with the
  length of the course, so a trunk carries more line than a headwater stub.
- **Deep crimson outline and tint** — a modelled flood zone. Red is deliberately not
  part of the water family: it is a forecast, not water.

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

# Layer order in the live pane

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
