"""CONVERGENCE per Slab2 zone, from a published plate-motion model (2026-11-23).

Model: Mueller et al. 2019 (Tectonics 38, 1884-1907, doi:10.1029/2018TC005462), plate motion model v2.0 "Updated"
(v2.02), CC BY 4.0, downloaded from
  https://www.earthbyte.org/webdav/ftp/Data_Collections/Muller_etal_2019_Tectonics/Muller_etal_2019_PlateMotionModel/Muller_etal_2019_PlateMotionModel_v2.0_Tectonics_Updated.zip
(SimplifiedFiles: CombinedRotations.rot + PlateBoundaries_DeformingNetworks.gpmlz), evaluated with pygplates 1.0.
MORVEL was preferred, but its primary file host (geoscience.wisc.edu/~chuck/MORVEL/) returns 404.

Per zone:
  trench point  Slab2 cells shallower than 15 km; median latitude (median longitude for E-W trending zones, see AXIS);
                in that row the shallowest cell (ties -> nearest the zone's median of the other coordinate).
  strike        principal axis of the shallow cells within 250 km (local tangent plane);
  down-dip      normal to strike, signed toward the slab's 40+ km cells within 300 km.
  plates        nearest resolved subduction-zone segment (rigid plate boundaries at 0 Ma) within 300 km:
                its overriding/subducting plates; fallback = plate under points 50 km seaward / 80 km landward.
  rate          velocity of the subducting plate relative to the overriding plate at the trench point,
                stage rotation 1 Ma -> 0 Ma. normal = component along down-dip (positive = convergence).
  age           Seton et al. 2020 age grid sampled 50 km seaward of the trench point.

Run: python3 _slabbake/motion_bake.py
"""
import glob, json, math, os, sys
import numpy as np
import pygplates

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import age_bake  # noqa: E402

SLAB = os.path.join(HERE, 'cache', 'Slab2Distribute_Mar2018', 'Slab2_TXT')
MDIR = os.path.join(HERE, 'cache', 'm19', 'x', 'Muller_etal_2019_PlateMotionModel_v2.0_Tectonics_Updated', 'SimplifiedFiles')
OUT = os.path.join(HERE, 'out', 'age', 'zones_motion.json')
ZONES = 'alu cal cam car cas cot hal hel him hin izu ker kur mak man mue pam phi png puy ryu sam sco sol sul sum van'.split()
CONTINENTAL = {'him': 'India-Eurasia continental collision (no oceanic plate at the front)',
               'hin': 'Hindu Kush: intracontinental slab beneath Eurasia, no plate boundary trench',
               'pam': 'Pamir: intracontinental slab beneath Eurasia, no plate boundary trench'}
FLAGS = {
    'phi': 'model carries the East Philippine Arc almost with the Philippine Sea plate, so trench convergence is only ~0.8 cm/yr; '
           'GPS-era studies put Philippine Trench convergence much higher -- treat as a model limitation',
    'mue': 'model has no plate boundary at the Muertos Trough (nearest model subduction 630 km); rate is Caribbean vs rigid '
           'North America reached landward, not a trough-local value',
    'puy': 'model has no subduction boundary at Puysegur (nearest 1300 km); overriding side is the Campbell deforming network',
    'cal': 'model moves Western Mediterranean (Calabria) with Africa: no resolvable convergence',
    'hal': 'Slab2 surface starts at 33 km; Molucca Sea double subduction -- over plate is the model\'s Celebes Sea plate',
    'ker': 'median point falls on the Kermadec segment; Tonga (PA vs TO microplate) is in checks',
    'izu': 'median point falls on the Mariana segment of the Izu-Bonin-Mariana zone',
}
ABBR = {901: 'PA', 821: 'TO', 801: 'AU', 911: 'NZ', 201: 'SA', 101: 'NA', 909: 'CO', 903: 'JF', 224: 'CA', 301: 'EU',
        501: 'IN', 503: 'AR', 701: 'AF', 709: 'SO', 608: 'PS', 659: 'IZ', 699: 'MA', 824: 'NFB', 818: 'SC', 815: 'SW',
        802: 'AN', 645: 'CS', 686: 'SFA', 607: 'BU', 847: 'NB', 697: 'NB2', 849: 'SOL', 653: 'CL', 781: 'MS', 678: 'EPA',
        674: 'WPA', 669: 'NSU', 566: 'SESU', 406: 'KAM', 511: 'CP', 970: 'RI', 708: 'WMED', 676: 'SBA', 664: 'NBA',
        829: 'WL', 923: 'JZ', 925: 'GP', 677: 'PAL', 646: 'SSU', 105: 'NA-oc', 6662: 'KUR'}
R = 6371.0


def enu(lat0, lon0, lat, lon):
    """Small-area tangent-plane km (east, north) of points relative to (lat0, lon0)."""
    dlon = (np.asarray(lon) - lon0 + 180) % 360 - 180
    return dlon * math.cos(math.radians(lat0)) * math.pi / 180 * R, (np.asarray(lat) - lat0) * math.pi / 180 * R


def offset(lat, lon, east_km, north_km):
    """Great-circle move from (lat, lon) by a local (east, north) km vector."""
    d = math.hypot(east_km, north_km) / R; az = math.atan2(east_km, north_km)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(az))
    l2 = l1 + math.atan2(math.sin(az) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 180) % 360 - 180


def load_zone(z):
    f = glob.glob(os.path.join(SLAB, '%s_slab2_dep_*.xyz' % z))
    assert len(f) == 1, (z, f)
    a = np.genfromtxt(f[0], delimiter=',')
    a = a[np.isfinite(a[:, 2])]
    a[:, 0] = (a[:, 0] + 180) % 360 - 180
    return a, os.path.basename(f[0])


def trench_point(a):
    sh = a[a[:, 2] > -15]
    if len(sh) == 0:
        return None
    lon0 = float(np.degrees(np.arctan2(np.sin(np.radians(sh[:, 0])).mean(), np.cos(np.radians(sh[:, 0])).mean())))
    dlon = (sh[:, 0] - lon0 + 180) % 360 - 180
    medlat = float(np.median(sh[:, 1])); medlon = lon0 + float(np.median(dlon))
    span_ns = (sh[:, 1].max() - sh[:, 1].min()); span_ew = (dlon.max() - dlon.min()) * math.cos(math.radians(medlat))
    axis = 'lat' if span_ns >= span_ew else 'lon'
    if axis == 'lat':
        row = sh[np.abs(sh[:, 1] - sh[np.argmin(np.abs(sh[:, 1] - medlat)), 1]) < 1e-6]
        other = np.abs(((row[:, 0] - medlon + 180) % 360) - 180)
    else:
        dl = (sh[:, 0] - medlon + 180) % 360 - 180
        tgt = dl[np.argmin(np.abs(dl))]
        row = sh[np.abs(dl - tgt) < 1e-6]
        other = np.abs(row[:, 1] - medlat)
    dmax = row[:, 2].max()
    cand = np.where(row[:, 2] >= dmax - 0.5)[0]
    k = cand[np.argmin(other[cand])]
    return dict(lat=float(row[k, 1]), lon=float(row[k, 0]), depth_km=float(-row[k, 2]), axis=axis,
                median_lat=round(medlat, 3), median_lon=round((medlon + 180) % 360 - 180, 3), n_shallow=int(len(sh)))


def geometry(a, tp):
    sh = a[a[:, 2] > -15]
    e, n = enu(tp['lat'], tp['lon'], sh[:, 1], sh[:, 0])
    m = np.hypot(e, n) < 250
    X = np.stack([e[m], n[m]], 1); X = X - X.mean(0)
    w, v = np.linalg.eigh(X.T @ X)
    s = v[:, np.argmax(w)]  # strike axis (east, north)
    normal = np.array([-s[1], s[0]])
    deep = a[a[:, 2] < -40]
    e2, n2 = enu(tp['lat'], tp['lon'], deep[:, 1], deep[:, 0])
    m2 = np.hypot(e2, n2) < 300
    if m2.sum() < 5:
        m2 = np.hypot(e2, n2) < 600
    dd = np.array([e2[m2].mean(), n2[m2].mean()])
    if normal @ dd < 0:
        normal = -normal
    strike_az = math.degrees(math.atan2(s[0], s[1])) % 180
    dip_az = math.degrees(math.atan2(normal[0], normal[1])) % 360
    return normal, strike_az, dip_az, int(m.sum())


def pick_row(a, target_lat):
    """Trench point at a given latitude (for named checks): shallowest cell in the row nearest target_lat."""
    sh = a[a[:, 2] > -15]
    r = sh[np.abs(sh[:, 1] - sh[np.argmin(np.abs(sh[:, 1] - target_lat)), 1]) < 1e-6]
    k = np.argmax(r[:, 2])
    return dict(lat=float(r[k, 1]), lon=float(r[k, 0]), depth_km=float(-r[k, 2]), axis='check')


def shallow_fallback(a):
    """Zones whose Slab2 surface never reaches 15 km: use cells within 15 km of the zone's shallowest depth."""
    top = a[:, 2].max()
    b = a.copy(); b[:, 2] = b[:, 2] - top - 0.001  # shift so the shallowest cell sits at ~0
    tp = trench_point(b)
    tp['depth_km'] = -top + tp['depth_km'] - 0.001
    return tp, float(-top), b


def main():
    rm = pygplates.RotationModel(os.path.join(MDIR, 'Muller_etal_2019_CombinedRotations.rot'))
    fc = pygplates.FeatureCollection(os.path.join(MDIR, 'Muller_etal_2019_PlateBoundaries_DeformingNetworks.gpmlz'))
    snap = pygplates.TopologicalModel(fc, rm).topological_snapshot(0)
    sections = snap.get_resolved_topological_sections(pygplates.ResolveTopologyType.boundary | pygplates.ResolveTopologyType.network)
    sz = []
    for sec in sections:
        if sec.get_feature().get_feature_type() == pygplates.FeatureType.gpml_subduction_zone:
            sz.extend(sec.get_shared_sub_segments())
    z = age_bake.load()

    def locate(lat, lon):
        """(kind, plate_id, topology name, velocity Vector3D cm/yr) of the rigid plate / deforming network at a point."""
        v, loc = snap.get_point_velocities([pygplates.PointOnSphere(lat, lon)], velocity_units=pygplates.VelocityUnits.cms_per_yr,
                                           return_point_locations=True)
        loc = loc[0]
        if loc.located_in_resolved_network():
            t = loc.located_in_resolved_network(); kind = 'network'
        elif loc.located_in_resolved_boundary():
            t = loc.located_in_resolved_boundary(); kind = 'rigid'
        else:
            return None
        return kind, t.get_feature().get_reconstruction_plate_id(), t.get_feature().get_name(), v[0]

    def rigid_vel(pid, pt):
        rot = rm.get_rotation(0.0, pid, 1.0)  # stage 1 -> 0 Ma, model's absolute frame
        return pygplates.calculate_velocities([pt], rot, 1.0, pygplates.VelocityUnits.cms_per_yr)[0]

    def solve(zn, a, tp):
        normal, strike_az, dip_az, nfit = geometry(a, tp)
        pt = pygplates.PointOnSphere(tp['lat'], tp['lon'])
        seg_km = round(min(pygplates.GeometryOnSphere.distance(pt, ss.get_resolved_geometry()) for ss in sz) * R, 1)
        sea_pts = [offset(tp['lat'], tp['lon'], -normal[0] * d, -normal[1] * d) for d in (50, 100, 150, 200)]

        def vel_at(c):
            return rigid_vel(c[1], pt) if c[0] == 'rigid' else c[3]
        S = L = None; skipped = []
        for q in sea_pts:
            cs = locate(*q)
            if not cs or cs[0] != 'rigid': continue  # the subducting plate must be a rigid (oceanic) plate
            vs = vel_at(cs)
            for d in (30, 80, 150, 250, 400, 600):
                ql = offset(tp['lat'], tp['lon'], normal[0] * d, normal[1] * d)
                c = locate(*ql)
                if not c or (c[1] == cs[1] and c[0] == cs[0]): continue
                if (vs - vel_at(c)).get_magnitude() < 0.5:  # moves with the subducting side: not the overriding plate
                    skipped.append('%s at %d km' % (c[2], d)); continue
                S, L = cs + (q,), c + (ql, d); break
            if S: break
        rec = dict(lat=round(tp['lat'], 3), lon=round(tp['lon'], 3), trench_depth_km=round(tp['depth_km'], 2),
                   pick_axis=tp['axis'], strike_deg=round(strike_az, 1), downdip_az_deg=round(dip_az, 1),
                   nearest_model_subduction_km=seg_km)
        rec['age_ma'] = None
        if zn not in CONTINENTAL:
            for q, d in zip(sea_pts, (50, 100, 150, 200)):
                age_v, _ = age_bake.sample(z, np.array([q[1]]), np.array([q[0]]))
                if np.isfinite(age_v[0]):
                    rec['age_ma'] = round(float(age_v[0]), 1); rec['age_sample_km'] = d; break
        if skipped:
            rec['skipped_landward'] = list(dict.fromkeys(skipped))
        if S is None:
            rec.update(sub=None, over=None, rate_cm_yr=None, normal_cm_yr=None,
                       note='model resolves no moving second plate within 600 km landward')
            return rec
        vs = rigid_vel(S[1], pt) if S[0] == 'rigid' else S[3]
        vo = rigid_vel(L[1], pt) if L[0] == 'rigid' else L[3]
        v = vs - vo
        ned = pygplates.LocalCartesian.convert_from_geocentric_to_north_east_down([pt], [v])[0]
        vn, ve = ned.get_x(), ned.get_y()
        rec.update(sub=ABBR.get(S[1], str(S[1])), over=ABBR.get(L[1], str(L[1])), sub_id=S[1], over_id=L[1],
                   sub_topology='%s (%s)' % (S[2], S[0]), over_topology='%s (%s)' % (L[2], L[0]),
                   over_probe_km=L[5], rate_cm_yr=round(math.hypot(vn, ve), 2),
                   normal_cm_yr=round(ve * normal[0] + vn * normal[1], 2),
                   velocity_az_deg=round(math.degrees(math.atan2(ve, vn)) % 360, 1))
        return rec

    zones = {}; rows = []
    for zn in ZONES:
        a, fname = load_zone(zn)
        tp = trench_point(a); note = None
        if tp is None:
            tp, top, a = shallow_fallback(a)
            note = 'no Slab2 cells shallower than 15 km (shallowest %.1f km); used cells within 15 km of the shallowest' % top
        rec = solve(zn, a, tp)
        if zn == 'him':  # collision front: rigid India against rigid Eurasia (the model's Tibet network sits between)
            pt = pygplates.PointOnSphere(rec['lat'], rec['lon'])
            v = rigid_vel(501, pt) - rigid_vel(301, pt)
            ned = pygplates.LocalCartesian.convert_from_geocentric_to_north_east_down([pt], [v])[0]
            vn, ve = ned.get_x(), ned.get_y(); az = math.radians(rec['downdip_az_deg'])
            rec.update(sub='IN', over='EU', sub_id=501, over_id=301, sub_topology='India from PB03 GS (rigid)',
                       over_topology='Eurasia_1_0 (rigid), rigid-plate pair across the Greater India network',
                       rate_cm_yr=round(math.hypot(vn, ve), 2), normal_cm_yr=round(ve * math.sin(az) + vn * math.cos(az), 2),
                       velocity_az_deg=round(math.degrees(math.atan2(ve, vn)) % 360, 1))
            rec.pop('over_probe_km', None); rec.pop('skipped_landward', None)
        if zn in ('hin', 'pam'):
            model_val = rec.get('rate_cm_yr')
            rec.update(sub=None, over=None, rate_cm_yr=None, normal_cm_yr=None,
                       model_network_rate_cm_yr=model_val)
        if zn in CONTINENTAL:
            rec['continental'] = True
            rec['note'] = CONTINENTAL[zn] + ('; ' + rec['note'] if rec.get('note') else '')
        if note:
            rec['note'] = note + ('; ' + rec['note'] if rec.get('note') else '')
        if zn in FLAGS:
            rec['flag'] = FLAGS[zn]
        zones[zn] = rec; rows.append((zn, rec))
    checks = {}
    for name, zn, la in (('northern_tonga', 'ker', -16.0), ('central_tonga', 'ker', -21.0), ('japan_trench', 'kur', 38.0),
                         ('chile_central', 'sam', -33.0)):
        a, _ = load_zone(zn)
        checks[name] = solve(zn, a, pick_row(a, la)); rows.append((name, checks[name]))
    doc = dict(
        source='Mueller, R.D. et al. (2019) A global plate model including lithospheric deformation along major rifts and '
               'orogens since the Triassic. Tectonics 38, 1884-1907, doi:10.1029/2018TC005462; plate motion model v2.0 '
               '(Updated, v2.02), 0 Ma topologies, stage rotation 1->0 Ma, via pygplates 1.0. '
               'https://www.earthbyte.org/webdav/ftp/Data_Collections/Muller_etal_2019_Tectonics/Muller_etal_2019_PlateMotionModel/'
               'Muller_etal_2019_PlateMotionModel_v2.0_Tectonics_Updated.zip . Ages: Seton, M. et al. (2020) G-Cubed '
               'doi:10.1029/2020GC009214, https://www.earthbyte.org/webdav/ftp/earthbyte/agegrid/2020/Grids/age.2020.1.GTS2012.6m.nc . '
               'Trench points: USGS Slab2 (Hayes et al. 2018).',
        license='Plate model: CC BY 4.0 (EarthByte Muller_etal_2019_Tectonics/License.txt). Age grid: CC BY 4.0 '
                '(EarthByte agegrid/2020/LICENSE.txt). Slab2: public domain (USGS).',
        method='rate = |v(sub rel. over)| at the Slab2 trench point; normal = component along the Slab2 down-dip direction '
               '(positive = convergence); age_ma sampled 50 km seaward. Two-plate rigid model: back-arc opening '
               '(e.g. Lau basin behind Tonga) is only present where the model carries the microplate.',
        zones=zones, checks=checks)
    with open(OUT, 'w') as f:
        json.dump(doc, f, indent=1)
    for zn, r in rows:
        print('%-15s %8.3f %8.3f %-5s %-5s %6s %6s %6s %6s | %s | %s | %s' % (zn, r['lat'], r['lon'], r.get('sub'), r.get('over'),
              r.get('rate_cm_yr'), r.get('normal_cm_yr'), r.get('age_ma'), r.get('nearest_model_subduction_km'),
              r.get('sub_topology'), r.get('over_topology'), r.get('note', '')))


if __name__ == '__main__':
    main()
