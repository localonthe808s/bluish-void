# ROAD MESH (national traffic view, z4-9)

A static road network drawn in the traffic tab's style, so the wide traffic view
shows the dense network (motorway, trunk/primary, secondary, tertiary) without
paying for about 1,000 TomTom flow tiles per view. TomTom's live layer still draws
the jams on top.

Source: our own Protomaps basemap (OpenStreetMap contributors),
`r2:bluishvoid-bg/basemap/bluish-basemap-20260829.pmtiles`, layer `roads`,
property `kind_detail`.

## Output

    https://cdn.bluishvoid.com/roads/mesh/v1/{z}/{x}/{y}.webp     z4-9
    https://cdn.bluishvoid.com/roads/mesh/v1/cover.json

* Transparent lossless WebP. Each tile covers 256 display px (Leaflet
  `tileSize: 256`, the default) but the image is 512 px, so retina screens get
  crisp lines; 1x screens downsample in the browser. Do NOT use `detectRetina`
  (it would halve every line width and jump a density step).
* Region: lower 48 + southern Canada, 24-56 N, -128 to -52.
* `cover.json` -> `cover`: the z6 tiles `[x, y]` that hold any road. Every z4-9
  tile under a cover z6 block exists (empty ones are tiny transparent tiles):
  a z7-9 tile exists iff its z6 ancestor is in the cover; a z4/z5 tile exists iff
  any of its z6 descendants is. Tiles outside the cover were never uploaded and
  the CDN caches 404s, so the page should not request them.

## Style (display px at the tile's own zoom)

| class | roads | casing | core |
|---|---|---|---|
| 0 | motorway (+ links) | rgba(8,10,16,.5) 4.0 | #05DB32 2.3 |
| 1 | trunk, primary (+ links) | 3.4 | #05DB32 1.7 |
| 2 | secondary (+ links) | 2.6 | rgba(5,219,50,.82) 1.2 |
| 3 | tertiary (+ links), drawn as class 2 | 2.6 | rgba(5,219,50,.82) 1.2 |

Casings of every class are drawn first into one layer composited at .5 (so
crossings do not stack alpha), then cores, motorways last.

Per output zoom (`ZOOM_PLAN` in bake.py), widths are multiplied by a scale,
judged against the TomTom z10 mock of the Northeast at z7:

| z | data zoom | classes | links | width scale |
|---|---|---|---|---|
| 4 | 8  | 0, 1        | no  | 0.50 |
| 5 | 9  | 0, 1        | no  | 0.56 |
| 6 | 9  | 0, 1, 2     | no  | 0.66 |
| 7 | 9  | 0, 1, 2     | no  | 0.80 |
| 8 | 10 | 0, 1, 2, 3  | yes | 0.90 |
| 9 | 11 | 0, 1, 2, 3  | yes | 1.00 |

Density check (`density.py`): the basemap carries secondary and tertiary in full
from data zoom 9 (z8 has neither), so z9+ data adds only geometric detail.
Tertiary at z7 turned the Northeast into a solid sheet; secondary alone matches
the TomTom z10 density there. Secondary at z5 crowded the Ohio Valley and the
Southeast, so z4-5 draw motorway/trunk/primary only.

Result (20261017): 8,457 tiles, 188 MB (z4 10, z5 32, z6 99, z7 396, z8 1,584,
z9 6,336); 99 cover blocks at z6. The bake ran 40 min on 8 procs.

## Commands

    # once: a local copy of the basemap (10.5 GB) and a venv
    rclone copy r2:bluishvoid-bg/basemap/bluish-basemap-20260829.pmtiles pm/ --s3-no-check-bucket --multi-thread-streams 16
    python3 -m venv rmvenv && rmvenv/bin/pip install pmtiles skia-python pillow numpy mapbox-vector-tile

    # bake (8 procs, about 40 min)
    rmvenv/bin/python -I _roadmesh/bake.py pm/bluish-basemap-20260829.pmtiles rm_out --procs 8

    # test tiles only
    rmvenv/bin/python -I _roadmesh/bake.py pm/bluish-basemap-20260829.pmtiles rm_test --only 7/37/47 7/38/47

    # judge against a page capture (anchor = NYC City Hall in tr_base.png, 2x capture)
    rmvenv/bin/python -I _roadmesh/compose.py rm_out tr_base.png preview.png --z 7

    # upload (the token cannot list buckets)
    rclone copy rm_out r2:bluishvoid-bg/roads/mesh/v1 --s3-no-check-bucket --transfers 32

    # verify only AFTER the upload (the CDN caches 404s)
    curl -sI https://cdn.bluishvoid.com/roads/mesh/v1/7/37/47.webp

A style change means a new version directory (`v2`), since tiles are cached hard.
`probe.py` tallies the road kinds of a tile (local PMTiles or tile URL).
