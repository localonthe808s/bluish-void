# State well lithology sources (WELLS layer)

Test any adapter: `cd /tmp && python3 -I /Users/vvvaa/bluish-void/_subbake/wells/test_src.py <code> [limit]`
Cache: `$WELLS_CACHE` (default /Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache)/<code>/

| code | state / source | usable | wells / intervals (tested) | licence (quoted) | coords | credit |
|---|---|---|---|---|---|---|
| tx | TWDB Groundwater Database, GWDBDownload.zip (83 MB, nightly) https://www.twdb.texas.gov/groundwater/data/data-well-reports.asp | yes | 7,187 / 96,192 | Public records. Disclaimer: "TWDB makes no guarantees or warranties as to the accuracy..." | GPS mostly, method in `loc` | Texas Water Development Board, Groundwater Database |
| txsdr | TWDB Submitted Drillers Reports, SDRDownload.zip (152 MB, nightly) | yes | 630,026 / 4,710,501 | Same page | Driller-placed; known-error rows dropped | Texas Water Development Board, Submitted Drillers Reports Database |
| ca | CA DWR Well Completion Reports + Geologic Logs CSVs https://data.cnra.ca.gov/dataset/well-completion-reports (454 MB, daily) | yes | 96,092 / 1,137,613 | "Other (Public Domain)" | Mostly PLSS section centroids (stacked dots) | California Department of Water Resources, Well Completion Reports (OSWCR) |
| mt | MT DNRC Source Aquifer Explorer Borehole Data FeatureServer (GWIC view) | yes | 178,475 / 1,146,714 | No licence text on the item; public records | Accuracy in `loc`; many TRS-derived | Montana Bureau of Mines and Geology, GWIC (via Montana DNRC) |
| wa | WA Geological Survey Subsurface database MapServer (DDS-11) | yes | 106,542 / 457,337 (mostly geotech borings; WELLS_WA_CLASSES=water) | Cite DDS-11; "as is" https://dnr.wa.gov/node/118 | Confidence in `loc` | Washington Geological Survey, Subsurface database (DDS-11) |
| or | OWRD GWIS lithology API per site (~10k sites) | yes, small | 300 / 5,401 (limit 300; full fetch ~2.5 h, resumable) | No licence text found; public records | GPS mostly | Oregon Water Resources Department, GWIS |
| co | CO DWR CDSS geophysical-log aquifer picks | marginal | 678 / 777 (partial; anonymous API gives 403 after ~975 requests) | Not checked in detail | PLSS-spotted | Colorado DWR, CDSS |
| ma | MassDEP Well Drillers layer (2023-04-26) + per-well generated report PDFs (text) | yes, slow | 100 / 236 (limit; ~83.4k candidates, ~58 h single-thread, MA_WORKERS) | "Permission is granted to copy and use the materials herein." | Parcel-level | MassDEP Well Driller Program well completion reports |
| ct | USGS CT Water Resources Bulletins depth-to-bedrock release (2021) | yes, coarse (<=2 intervals) | 9,653 / 14,939 | USGS: useconst "None." | DMS from bulletins (~30 m) | USGS, depth to bedrock from CT Water Resources Bulletins |
| nyli | USGS Long Island framework data points (Finkelstein 2024) + NWIS altitudes | yes, hydrogeologic units | 622 / 2,271 | "None. Acknowledgement of the U.S. Geological Survey would be appreciated" | NAD83 | USGS, Finkelstein and others (2024) |
| nj | NJGS / NJDEP | NO | - | Logs are paper "available upon request"; DGS97-1 withdrawn; DataMiner unreachable | - | - |
| ny | NYSDEC Water Wells (144k) | NO | - | Lithology only in scanned report PDFs | - | - |
| ut | Utah DWRi | NO | - | No lithology fields; scans only | - | - |
| az | ADWR GWSI | unverified | - | azwater.gov/gis 403s; GWSI may hold lithology | - | - |
| pa, oh, in, il, mi | Midwest-east survey | PENDING | adapters present: src_pa, src_in, src_il, src_mi (not yet reported/verified) | - | - | - |
| ks, ksog, mn, ia, wi, ne | Plains survey | PENDING | adapters present: src_ks, src_ksog, src_mn, src_ia (not yet reported/verified) | - | - | - |


**Nebraska (CSD test holes): not used, by the user's decision (2026-11-08). The adapter was removed; the licence also forbids redistribution without permission.**

**Second bake (2026-11-09): live, 3,669,438 wells, 29,326 log cells, 211 MB pmtiles.** Added mi (1,172,061, EGLE Wellogic, "no restrictions on the use, reproduction, or distribution"), ia (19,512, IGS GeoSam crawl, credit IGS), or (6,329, OWRD GWIS). PA / IN / IL / KS / KSOG / MN / WI verified (rows above marked PENDING are done). NGWMN still has 5,594 logs unfetched (www.usgs.gov blocked this machine's IP on 11-08): fetch them from GitHub Actions, 2 workers, then rebake.
