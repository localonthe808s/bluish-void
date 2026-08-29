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
4. *Skeletonised* to centre-lines, broken at junctions, then re-stitched where
   ends meet and keep the same heading; simplified to ~13 m.
5. *Named* by nearest match to the old hand-traced draft (320 m tolerance).
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

Three marks, and nothing else:

- **Solid blue fill** — water that is still there. That comes from the basemap, not
  from this layer.
- **Bright blue line with a red edge** — a buried watercourse. The red is an outline,
  not a second line: it is what keeps a two-pixel course legible over the orange
  borough mask and the green parks, and it marks the course as something drawn onto
  the city rather than something running through it.
- **Pale wash with a faint blue edge** — the marsh and meadow the course ran through.
  It is semi-transparent, so it takes a sage cast over parkland and a warm one over
  built ground; the land under it still reads.

Both course strokes are **solid**. Dashing them both put a round cap on either end of
every dash, so each course came out as a string of beads in red shells rather than a
line. The wash needs its edge for the same reason — without one it reads as a smudge.

A course does not always run the length of its marsh: the centreline is only kept
where the wet ground was narrow enough to have been a channel, so a broad marsh is
drawn as an area with no line through it, and a neck between two marshes gets a line.
That is deliberate, not a gap.
