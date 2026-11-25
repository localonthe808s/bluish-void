#!/bin/bash
# THE HAZARD YEARS video, data (2026-11-25): IBTrACS since 1980 (NOAA NCEI) + USGS ComCat M5+ worldwide 1980-2025
cd "$(dirname "$0")/cache"
curl -s -m 600 -o ibtracs.csv "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.since1980.list.v04r01.csv"
for y in 1980 1985 1990 1995 2000 2005 2010 2015 2020; do e=$((y+5)); [ $e -gt 2026 ] && e=2026
  curl -s -m 300 -o q_$y.csv "https://earthquake.usgs.gov/fdsnws/event/1/query?format=csv&starttime=$y-01-01&endtime=$e-01-01&minmagnitude=5&orderby=time-asc&limit=20000"; done
ls -la
