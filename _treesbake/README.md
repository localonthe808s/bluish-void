# NATIONAL STREET TREES bake

The same tiles THE CITY's NYC STREET TREES card reads (`/trees/`, `_maplab/trees_bake.py`), for every other US city
with a public tree inventory, on R2 at `https://cdn.bluishvoid.com/trees/v1/`.

## Source and license

McCoy, D. et al. (2022). *A dataset of
5 million city trees from 63 US cities: species, location, nativity status, health, and more.* Dryad,
doi:10.5061/dryad.2jm63xsrf. Zenodo mirror: https://zenodo.org/records/6726506 (the files used here).
**License: CC0 1.0** (Dryad's `license` field: https://spdx.org/licenses/CC0-1.0.html; Zenodo: `cc-zero`).
Credit the paper anyway (eLife 2022, "Species clustering, climate effects, and introduced species in 5 million
city trees across 63 US cities").

## Commands (run from the repo root)

```sh
S=/tmp/trees_national          # anywhere outside the repo
python3 -I _treesbake/fetch.py   $S/mccoy                                   # 63 CSVs minus New York, ~550 MB; rerun to retry failures
python3 -I _treesbake/profile.py $S/mccoy > $S/profile.json                 # optional: per-city columns, fill rates
python3 -I _treesbake/bake.py    $S/mccoy $S/out trees/index.json           # ~25 min
# only when the naming rules change: re-vote latin -> common from a bake, then bake again
python3 -I _treesbake/names.py   $S/out trees/index.json > _treesbake/latin_common.json
python3 -I _treesbake/season.py  $S/out index.html                          # season.json + shifts into cities.json + coverage report
                                                                            # (season text: season_data.py; shifts: shifts.py)
rclone copy $S/out r2:bluishvoid-bg/trees/v1 --s3-no-check-bucket --transfers 32
```

The R2 token cannot list buckets (hence `--s3-no-check-bucket`), and the CDN caches 404s: never request a
`cdn.bluishvoid.com/trees/v1/...` URL before it is uploaded.

## Output (`trees/v1/`)

* `cities.json` `[{slug, name, state, bbox:[w,s,e,n], n, year, nbhd, rank_unit, center:[lat,lon], key, shift:[spring, fall]}]`
* `<slug>/index.json`, `<slug>/t_<floor(lat/0.01)>_<floor(lon/0.01)>.json`, `<slug>/nta.json` -- NYC's exact format
  (see the docstring of `bake.py`); `index.json` adds `city`, `state`, `year`.
* `season.json` -- `{name: {p, b, f, t, ev}}` for species CW_TREE_SEASON lacks, in New York's calendar.

### Differences from NYC

* `tree_id` is the dataset's `tree_ID` (or the CSV row number); there is no city API to ask for the full record.
* `nta.json` rows are `[name, name, "", live, hectares, good_share, top3]`: code = name, no borough, and the
  denominator is the count of 100 m grid squares (1 ha each) holding any of the neighborhood's trees -- NYC's
  "blocks that hold a tree" on a grid -- not census blocks. `rank_unit` says so; `median` is trees a hectare
  over neighborhoods of 30 or more such hectares. (A convex hull was tried and failed: mislabeled trees
  stretched hulls across town.) Cities without a neighborhood field
  have `nta: []`, `median: null`, `rank_unit: null`. Only Denver, Minneapolis, Pittsburgh and Durham have one.
* `hs`: excellent/good 0, fair 1, poor/critical/dying 2, missing 3, dead and dead/dying 4, stump 5. Empty
  planting sites are dropped; most cities record no condition (hs 3).
* DBH: cm / 2.54, rounded to whole inches.
* Trees: coordinates required, retired trees dropped, `location_type == green_space` (parks, golf courses)
  dropped; anything 60 km from the city's median point dropped.
* Unlocated trees: more than 25 trees on one exact coordinate are a geocoder's fallback (a street or zip
  centroid), not located trees, and would draw as a phantom grove; they are dropped and counted in
  `unlocated` (cities.json and index.json). It is large in Minneapolis, Houston, Sacramento, Stockton,
  Ontario, Overland Park and Rochester.
* Los Angeles coordinates are rounded to about 0.001 degree (~100 m) for some trees; the 200 m count holds,
  the nearest tree does not.
* Species: one entry per common name; names follow NYC's wording where NYC has the species (so
  CW_TREE_SEASON hits), else a cross-city vote (`latin_common.json`) and a few aliases in `bake.py`.
* `year`: the 5th-95th percentile of the inventory's `most_recent_observation` years, `null` if undated.
* Season: CW_TREE_SEASON and season.json are New York's calendar; add `shift[0]` to p and b and `shift[1]` to
  f for a city (`shifts.py`). Honolulu's fall shift is `null` (no fall).

### Cities skipped

No coordinates in the dataset: Boston, Dallas, Fresno, Grand Rapids, Indianapolis, Irvine, Jersey City, Miami,
New Orleans, Orlando, Phoenix, Plano, Richmond, Worcester. Too few located trees after the stack rule:
Nashville (488 located, 1,571 stacked). New York: THE CITY's own 2015 census. 47 cities, 3,320,107 trees.
