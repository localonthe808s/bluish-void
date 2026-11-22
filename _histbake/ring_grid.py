"""The one grid both ring steps share: lon -74.5..-73.25, lat 40.5..41.0 at 0.00008 deg (8.9 m N-S, 6.8 m E-W), NAD27-free lon/lat."""
from rasterio.transform import from_origin
RES = 0.00008
W0, S0, E0, N0 = -74.5, 40.5, -73.25, 41.0
NX, NY = int(round((E0 - W0) / RES)), int(round((N0 - S0) / RES))
T = from_origin(W0, N0, RES, RES)
