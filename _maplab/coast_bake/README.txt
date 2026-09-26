THE COAST view's relief/seafloor (city_bathy_coast.png) and INCOMING's ocean framing (city_terrain_inc_sea.png).
The original NE/INCOMING bake scripts were lost, so the LOOK was learned back off the shipped rasters:

  lut2.py learn <existing.png> <X0,Y0,X1,Y1> <gmrt.nc> <prefix>   -> <prefix>_land.npy / _sea.npy lookup tables
  lut2.py bake  <X0,Y0,X1,Y1> <W> <H> <gmrt.nc> <prefix> <out.png> -> a new box in that look
  bake_coast2.py -> THE COAST v2: land from lut_land.npy; sea drawn fresh (GMRT med + max over the Hudson Canyon,
                    2x supersampled depth ramp, exaggerated multi-light relief, isobaths). Needs, in the working dir:
    gmrt_med.nc  : GridServer ?minlongitude=-81&maxlongitude=-63.5&minlatitude=33&maxlatitude=46&format=netcdf&resolution=med&layer=topo
    t_canyon.nc  : GridServer ?minlongitude=-74.3&maxlongitude=-71.3&minlatitude=38.8&maxlatitude=40.6&format=netcdf&resolution=max&layer=topo
  (GridServer base https://www.gmrt.org/services/GridServer ; resolution=high 404s, med and max work.)
Tables: lut_land/lut_sea = learned off city_bathy_ne.png; inc_land/inc_sea = off city_terrain_inc.png.
Verify any box against GIBS MODIS_Terra_L3_Land_Water_Mask (EPSG:3857 WMS): coast 98.9% within 1 px, inc_sea 98.4% at 0.

v3 (2026-09-25): bake_coast3.py -> city_bathy_coast.webp. Adds GMRT max tiles t_south.nc (-73.8..-70.8, 37.2..38.9),
t_west.nc (-76.0..-73.3, 36.8..39.2), t_east.nc (-71.4..-68.3, 38.8..41.0) beside t_canyon.nc; each smoothed to the
output footprint before sampling (anti-alias), a row-coherent destripe over the flat abyss (the regional grid carries a
~1.8 m, ~6 km row pattern), depth-growing exaggeration and a texture term; shipped as WebP q92 (the 256-colour PNG
posterised the ramp). trace2.py follows the Hudson Canyon's strongest incision from the head to where the cut fades
(needs coast3_Z2x.npy, written by the bake): 343 km, head 39.67N 72.49W (139 m) -> 37.66N 70.51W (4,108 m).
v4 (2026-09-25): bake_coast4.py -> the incision look the user preferred; reads coast3_Z2x.npy (run bake_coast3.py first).
v5: bake_coast4.py adds a 2.5 km incision scale + raised-ground highlight; retrace.py snaps the canyon course to the thalweg on the 46 m tiles (reads canyon_trace2.json from trace2.py).
