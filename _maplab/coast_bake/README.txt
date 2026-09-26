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
