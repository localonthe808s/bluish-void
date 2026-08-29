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
