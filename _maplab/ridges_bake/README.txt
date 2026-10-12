THE RIDGES view (2026-10-11): box X -9039143..-8165285, Y 4533831..5300037 (lon -81.2..-73.35, lat 37.68..42.92), 1.1405 like cw-body.

Inputs (put in ./dl):
  gmrt_ridges.nc : GMRT GridServer ?minlongitude=-81.6&maxlongitude=-72.9&minlatitude=37.3&maxlatitude=43.3&format=netcdf&resolution=med&layer=topo
  physio/        : USGS physio_shp.zip (https://water.usgs.gov/GIS/dsdl/physio_shp.zip), Fenneman & Johnson 1946
  lwmask.png     : GIBS WMS MODIS_Terra_L3_Land_Water_Mask, EPSG:3857, the box above, 2264x1985

Relief: ../coast_bake/lut2.py bake <box> 2264 1985 dl/gmrt_ridges.nc inc out.png (INCOMING's learned look), then lakes cut
transparent where the MODIS mask says water and GMRT says land (Erie, Finger Lakes, rivers) so our map's water shows;
quantize(160, FASTOCTREE, no dither) -> city_terrain_ridges.png.
Geology: geo_extract.py (provinces -> prov.pkl) then geo_build.py -> city_ridges_geo.json: belts with median elevation,
the Allegheny Front (plateau/valley-and-ridge boundary, first run only: past -76.06 it hooks round the anthracite valleys),
the mountains' eastern foot, the Fall Line, and three live sample points with the Front's east-pointing normal.
front_snap.py measured the USGS line vs the steepest slope: median 4.5 km off, so it draws as a soft band. Rise across it
measured at 40 points: median 384 m (~1,300 ft).
Zones: zones_fetch.py <out.json> -> every OH/WV/VA/MD/PA forecast+county zone touching the box, merged into city_ne_zones.json.
Weather lines (2026-10-11): geo_more.py gives each belt two lines on what it does to the weather and names the Catskills and the
Hudson Valley with theirs. (A first pass with rock ages and glacial limits was rejected: weather and storm spots only.)
Run it on the geo_build.py output, not on its own output twice.
