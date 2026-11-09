"""Inverse UTM (GRS80/WGS84 ellipsoid, northern hemisphere) -> (lat, lon) degrees. Pure python, ~mm accuracy."""
import math

_a = 6378137.0; _f = 1 / 298.257222101; _k0 = 0.9996
_e2 = _f * (2 - _f); _ep2 = _e2 / (1 - _e2)
_e1 = (1 - math.sqrt(1 - _e2)) / (1 + math.sqrt(1 - _e2))


def to_ll(e, n, zone):
    x = e - 500000.0; y = n
    m = y / _k0
    mu = m / (_a * (1 - _e2 / 4 - 3 * _e2 ** 2 / 64 - 5 * _e2 ** 3 / 256))
    p = (mu + (3 * _e1 / 2 - 27 * _e1 ** 3 / 32) * math.sin(2 * mu) + (21 * _e1 ** 2 / 16 - 55 * _e1 ** 4 / 32) * math.sin(4 * mu)
         + (151 * _e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * _e1 ** 4 / 512) * math.sin(8 * mu))
    sp, cp, tp = math.sin(p), math.cos(p), math.tan(p)
    c1 = _ep2 * cp ** 2; t1 = tp ** 2
    n1 = _a / math.sqrt(1 - _e2 * sp ** 2)
    r1 = _a * (1 - _e2) / (1 - _e2 * sp ** 2) ** 1.5
    d = x / (n1 * _k0)
    lat = p - (n1 * tp / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * _ep2) * d ** 4 / 24
                                + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * _ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * _ep2 + 24 * t1 ** 2) * d ** 5 / 120) / cp
    return math.degrees(lat), (zone - 1) * 6 - 180 + 3 + math.degrees(lon)
