/* bvDSWx -- standalone "radar-seen surface water" overlay: NASA OPERA DSWx-S1
 * (Dynamic Surface Water Extent from Sentinel-1 SAR), drawn on a Leaflet 1.x map.
 *
 * Source: NASA/JPL OPERA, archived at PO.DAAC (public). Required credit:
 *   "Contains modified Copernicus Sentinel data <year>" + NASA/JPL OPERA.
 *   Discovery: CMR granule search (CORS-open). One granule = one MGRS tile.
 *   Picture:   the granule's 1024x1024 palette BROWSE.png (no CORS header -> drawn, never read).
 *
 * Browse palette (seen across 18 tiles, 9 regions, 2026-09-23):
 *   (0,0,255)     open water
 *   (0,255,0)     inundated vegetation
 *   (255,255,255) not water (some tiles leave it transparent instead)
 *   (120,120,240) partial water (palette entry, never seen used by S1)
 *   transparent   no data / masked (HAND, layover-shadow, outside the swath)
 *
 * Tile geometry -- two different squares, both 109.8 km, in the UTM zone of the tile id:
 *   - the CMR envelope is the lat/lon box of a square with upper-left (sqW - 4900, sqN + 4900)
 *     (sqW/sqN = west/north edge of the MGRS 100 km square). Fitted on 12 tiles, 5 continents,
 *     to < 2 m. It is only used to find the 100 km square (and checked: fitErr, metres).
 *   - the BROWSE IMAGE spans the Sentinel-2 tile: upper-left (E0, N0) = (sqW - 20, sqN + 20).
 *     Measured by matching browse water to basemap water on 5 NYC tiles: best fit within
 *     5-50 m of this corner (a third of a 107 m browse pixel); the envelope square is 4.9 km off.
 *   Image point (u, v) in pixels (edges) -> UTM (E0 + u*S, N0 - v*S), S = 109800/1024.
 *
 * API (window.bvDSWx):
 *   find(bounds, days=40)      -> Promise [{title, tile, time, produced, sensor, browse, envelope,
 *                                 zone, south, E0, N0 (browse upper-left, UTM m), fitErr, coverage, track}],
 *                                 newest first, one per tile+time
 *                                 bounds: L.LatLngBounds | [[s,w],[n,e]] | {west,south,east,north}
 *                                 coverage = % of the tile the pass observed (CMR SpatialCoverage),
 *                                 track = Sentinel-1 relative orbit
 *   latestPass(bounds, days, {minCoverage}) -> Promise of the newest pass's granules (same UTC
 *                                 acquisition date); minCoverage (%) skips swath-edge slivers
 *   groupPasses(granules)      -> [{date:'YYYY-MM-DD', time, granules}], newest first
 *   newestPerTile(granules)    -> the newest granule of every tile (a mosaic across passes)
 *   layer(granules, opts)      -> L.Layer (canvas in the overlay pane, mesh-warped UTM -> Web Mercator)
 *       opts.opacity  0.85 | opts.color '#1f6fe0' (water) | opts.vegColor '#2e9e62' or null (hide)
 *       opts.mesh 32 (cells per side) | opts.smooth true | opts.pane 'overlayPane'
 *       layer.setOpacity(x), layer.setGranules(list)
 *   credit(granules)           -> short HTML credit (pass dates, Copernicus + OPERA, dataset link)
 *   utm: {forward(lat, lon, zone, south) -> [E, N], inverse(E, N, zone, south) -> [lat, lon]}
 *   tileCorners(granule)       -> [[lat,lon] x4] UL, UR, LR, LL
 *   pixelLatLng(granule, i, j) -> [lat, lon] of browse pixel centre (i column, j row)
 * Plain ES5, no dependencies except Leaflet for layer().
 */
(function () {
  'use strict';

  var CMR = 'https://cmr.earthdata.nasa.gov/search/granules.umm_json';
  var SHORT = 'OPERA_L3_DSWX-S1_V1';
  // podaac.jpl.nasa.gov/dataset/OPERA_L3_DSWX-S1_V1 timed out (curl and Chrome) on 2026-09-23; JPL's page loads.
  var DATASET_URL = 'https://www.jpl.nasa.gov/go/opera/products/dswx-product-suite/';
  var TILE_M = 109800, IMG = 1024, MARGIN = 4900, S2_OFF = 20;
  var S = TILE_M / IMG;

  /* ---------------- UTM: Transverse Mercator, WGS84, Krueger series to n^6 (Karney 2011) ---------------- */
  var a = 6378137, f = 1 / 298.257223563, k0 = 0.9996;
  var e = Math.sqrt(f * (2 - f)), n = f / (2 - f);
  var n2 = n * n, n3 = n2 * n, n4 = n3 * n, n5 = n4 * n, n6 = n5 * n;
  var A = a / (1 + n) * (1 + n2 / 4 + n4 / 64 + n6 / 256);
  var ALPHA = [0,
    n / 2 - 2 * n2 / 3 + 5 * n3 / 16 + 41 * n4 / 180 - 127 * n5 / 288 + 7891 * n6 / 37800,
    13 * n2 / 48 - 3 * n3 / 5 + 557 * n4 / 1440 + 281 * n5 / 630 - 1983433 * n6 / 1935360,
    61 * n3 / 240 - 103 * n4 / 140 + 15061 * n5 / 26880 + 167603 * n6 / 181440,
    49561 * n4 / 161280 - 179 * n5 / 168 + 6601661 * n6 / 7257600,
    34729 * n5 / 80640 - 3418889 * n6 / 1995840,
    212378941 * n6 / 319334400];
  var BETA = [0,
    n / 2 - 2 * n2 / 3 + 37 * n3 / 96 - n4 / 360 - 81 * n5 / 512 + 96199 * n6 / 604800,
    n2 / 48 + n3 / 15 - 437 * n4 / 1440 + 46 * n5 / 105 - 1118711 * n6 / 3870720,
    17 * n3 / 480 - 37 * n4 / 840 - 209 * n5 / 4480 + 5569 * n6 / 90720,
    4397 * n4 / 161280 - 11 * n5 / 504 - 830251 * n6 / 7257600,
    4583 * n5 / 161280 - 108847 * n6 / 3991680,
    20648693 * n6 / 638668800];
  var D2R = Math.PI / 180;

  function atanh(x) { return 0.5 * Math.log((1 + x) / (1 - x)); }
  function asinh(x) { return Math.log(x + Math.sqrt(x * x + 1)); }
  function sinh(x) { return (Math.exp(x) - Math.exp(-x)) / 2; }
  function cosh(x) { return (Math.exp(x) + Math.exp(-x)) / 2; }
  function cm(zone) { return (zone * 6 - 183) * D2R; }

  function utmForward(lat, lon, zone, south) {
    var phi = lat * D2R, lam = lon * D2R - cm(zone);
    var tau = Math.tan(phi);
    var sig = sinh(e * atanh(e * tau / Math.sqrt(1 + tau * tau)));
    var taup = tau * Math.sqrt(1 + sig * sig) - sig * Math.sqrt(1 + tau * tau);
    var cl = Math.cos(lam);
    var xip = Math.atan2(taup, cl);
    var etap = asinh(Math.sin(lam) / Math.sqrt(taup * taup + cl * cl));
    var xi = xip, eta = etap;
    for (var j = 1; j <= 6; j++) {
      xi += ALPHA[j] * Math.sin(2 * j * xip) * cosh(2 * j * etap);
      eta += ALPHA[j] * Math.cos(2 * j * xip) * sinh(2 * j * etap);
    }
    return [500000 + k0 * A * eta, k0 * A * xi + (south ? 10000000 : 0)];
  }

  function utmInverse(E, N, zone, south) {
    var xi = (N - (south ? 10000000 : 0)) / (k0 * A), eta = (E - 500000) / (k0 * A);
    var xip = xi, etap = eta;
    for (var j = 1; j <= 6; j++) {
      xip -= BETA[j] * Math.sin(2 * j * xi) * cosh(2 * j * eta);
      etap -= BETA[j] * Math.cos(2 * j * xi) * sinh(2 * j * eta);
    }
    var she = sinh(etap), cx = Math.cos(xip);
    var taup = Math.sin(xip) / Math.sqrt(she * she + cx * cx);
    var lam = Math.atan2(she, cx);
    var tau = taup, e2m = 1 - e * e;
    for (var i = 0; i < 5; i++) {
      var s1 = Math.sqrt(1 + tau * tau);
      var sig = sinh(e * atanh(e * tau / s1));
      var ti = tau * Math.sqrt(1 + sig * sig) - sig * s1;
      var d = (taup - ti) / Math.sqrt(1 + ti * ti) * (1 + e2m * tau * tau) / (e2m * s1);
      tau += d;
      if (Math.abs(d) < 1e-13) break;
    }
    return [Math.atan(tau) / D2R, (lam + cm(zone)) / D2R];
  }

  /* ---------------- granule geometry ---------------- */
  function tileLatLng(g, u, v) { return utmInverse(g.E0 + u * S, g.N0 - v * S, g.zone, g.south); }

  // lat/lon envelope of the tile square (edges sampled densely; TM edges curve slightly)
  function squareEnvelope(zone, south, E0, N0) {
    var w = 180, s = 90, ea = -180, no = -90, k = 24;
    for (var i = 0; i <= k; i++) {
      var t = i / k * TILE_M;
      var pts = [[E0 + t, N0], [E0 + t, N0 - TILE_M], [E0, N0 - t], [E0 + TILE_M, N0 - t]];
      for (var p = 0; p < 4; p++) {
        var ll = utmInverse(pts[p][0], pts[p][1], zone, south);
        if (ll[1] < w) w = ll[1]; if (ll[1] > ea) ea = ll[1];
        if (ll[0] < s) s = ll[0]; if (ll[0] > no) no = ll[0];
      }
    }
    return { west: w, south: s, east: ea, north: no };
  }

  function envErrM(a1, b1) {
    var lat = (a1.south + a1.north) / 2, kx = 111320 * Math.cos(lat * D2R), ky = 110574;
    return Math.max(Math.abs(a1.west - b1.west) * kx, Math.abs(a1.east - b1.east) * kx,
      Math.abs(a1.south - b1.south) * ky, Math.abs(a1.north - b1.north) * ky);
  }

  // Upper-left UTM corner of the browse image from the tile id + the CMR envelope. The envelope
  // centre lands within a few km of the 100 km square's centre, so rounding to the 100 km grid is
  // unambiguous; the envelope square is then checked against the CMR box (fitErr, metres) and the
  // image corner is the Sentinel-2 tile corner of that square (see the header).
  function fitCorner(g) {
    var env = g.envelope;
    var lonC = (env.west + env.east) / 2;
    if (env.west > env.east) lonC = ((env.west + env.east + 360) / 2 + 540) % 360 - 180;
    var c = utmForward((env.south + env.north) / 2, lonC, g.zone, g.south);
    var sqW = Math.round((c[0] - 50000) / 1e5) * 1e5, sqS = Math.round((c[1] - 50000) / 1e5) * 1e5;
    var err = envErrM(squareEnvelope(g.zone, g.south, sqW - MARGIN, sqS + 1e5 + MARGIN), env);
    g.E0 = sqW - S2_OFF; g.N0 = sqS + 1e5 + S2_OFF;
    g.fitErr = Math.round(err * 10) / 10;   // > ~100 m would mean the square was misidentified
    return g;
  }

  function tileCorners(g) {
    return [tileLatLng(g, 0, 0), tileLatLng(g, IMG, 0), tileLatLng(g, IMG, IMG), tileLatLng(g, 0, IMG)];
  }
  function pixelLatLng(g, i, j) { return tileLatLng(g, i + 0.5, j + 0.5); }

  /* ---------------- CMR discovery ---------------- */
  var TITLE_RE = /_T(\d\d)([C-X])([A-Z]{2})_(\d{8}T\d{6})Z_(\d{8}T\d{6})Z_(S1[A-Z])_/;
  function parseStamp(s) {
    return Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8), +s.slice(9, 11), +s.slice(11, 13), +s.slice(13, 15));
  }

  function normBounds(b) {
    if (!b) throw new Error('bvDSWx: bounds required');
    if (typeof b.getWest === 'function') return { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() };
    if (b.length === 2) return { west: b[0][1], south: b[0][0], east: b[1][1], north: b[1][0] };
    return { west: b.west, south: b.south, east: b.east, north: b.north };
  }

  function parseItem(it) {
    var u = it.umm || {};
    var title = u.GranuleUR || '';
    var m = TITLE_RE.exec(title);
    if (!m) return null;
    var browse = null, urls = u.RelatedUrls || [];
    for (var i = 0; i < urls.length; i++) {
      var url = urls[i].URL || '';
      if (/^https:/.test(url) && /_BROWSE\.png$/.test(url)) { browse = url; break; }
    }
    var rects = (((u.SpatialExtent || {}).HorizontalSpatialDomain || {}).Geometry || {}).BoundingRectangles || [];
    if (!browse || !rects.length) return null;
    var r = rects[0];
    var attrs = {}, aa = u.AdditionalAttributes || [];
    for (var k = 0; k < aa.length; k++) attrs[aa[k].Name] = (aa[k].Values || [])[0];
    var trk = /_T(\d{3})-\d+-IW/.exec((u.InputGranules || [])[0] || '');
    var g = {
      title: title, tile: 'T' + m[1] + m[2] + m[3], zone: +m[1], south: m[2] < 'N',
      time: parseStamp(m[4]), produced: parseStamp(m[5]), sensor: m[6], browse: browse,
      coverage: attrs.SpatialCoverage != null ? +attrs.SpatialCoverage : null,   // % of the tile observed
      track: trk ? +trk[1] : null,                                               // Sentinel-1 relative orbit
      envelope: { west: r.WestBoundingCoordinate, south: r.SouthBoundingCoordinate, east: r.EastBoundingCoordinate, north: r.NorthBoundingCoordinate }
    };
    return fitCorner(g);
  }

  function fetchPage(url, after) {
    var opts = after ? { headers: { 'CMR-Search-After': after } } : {};
    return fetch(url, opts).then(function (r) {
      if (!r.ok) throw new Error('CMR HTTP ' + r.status);
      var next = r.headers.get('CMR-Search-After');
      return r.json().then(function (j) { return { items: j.items || [], next: next, hits: +r.headers.get('CMR-Hits') || 0 }; });
    });
  }

  function find(bounds, days) {
    var b = normBounds(bounds);
    days = days == null ? 40 : days;
    var start = new Date(Date.now() - days * 864e5).toISOString().slice(0, 19) + 'Z';
    var url = CMR + '?short_name=' + SHORT + '&bounding_box=' + [b.west, b.south, b.east, b.north].map(function (x) { return (+x).toFixed(5); }).join(',') +
      '&temporal=' + encodeURIComponent(start + ',') + '&sort_key=-start_date&page_size=200';
    var all = [];
    function step(after, pages) {
      return fetchPage(url, after).then(function (p) {
        all = all.concat(p.items);
        if (p.next && p.items.length === 200 && pages < 5) return step(p.next, pages + 1);
        return all;
      });
    }
    return step(null, 1).then(function (items) {
      // reprocessed duplicates (same tile, acquisition within 2 min; the stamp can differ by 1 s):
      // keep the newest production
      var out = [];
      for (var i = 0; i < items.length; i++) {
        var g = parseItem(items[i]);
        if (!g) continue;
        var dup = -1;
        for (var j = 0; j < out.length; j++) if (out[j].tile === g.tile && Math.abs(out[j].time - g.time) < 120000) { dup = j; break; }
        if (dup < 0) out.push(g);
        else if (out[dup].produced < g.produced) out[dup] = g;
      }
      out.sort(function (x, y) { return y.time - x.time || (x.tile < y.tile ? -1 : 1); });
      return out;
    });
  }

  function ymdOf(t) { return new Date(t).toISOString().slice(0, 10); }

  function groupPasses(granules) {
    var map = {}, list = [];
    for (var i = 0; i < granules.length; i++) {
      var d = ymdOf(granules[i].time);
      if (!map[d]) { map[d] = { date: d, time: granules[i].time, granules: [] }; list.push(map[d]); }
      map[d].granules.push(granules[i]);
      if (granules[i].time > map[d].time) map[d].time = granules[i].time;
    }
    list.sort(function (x, y) { return y.time - x.time; });
    return list;
  }

  // opts.minCoverage (percent): skip passes whose best tile saw less than this much of its tile
  // (CMR SpatialCoverage). Tile-level, not bounds-level: a swath edge can still miss the bounds.
  function latestPass(bounds, days, opts) {
    var minCov = (opts && opts.minCoverage) || 0;
    return find(bounds, days).then(function (gs) {
      var p = groupPasses(gs);
      for (var i = 0; i < p.length; i++) {
        var best = 0;
        for (var j = 0; j < p[i].granules.length; j++) best = Math.max(best, p[i].granules[j].coverage == null ? 100 : p[i].granules[j].coverage);
        if (best >= minCov) return p[i].granules;
      }
      return [];
    });
  }

  function newestPerTile(granules) {
    var seen = {}, out = [];
    var s = granules.slice().sort(function (x, y) { return y.time - x.time; });
    for (var i = 0; i < s.length; i++) if (!seen[s[i].tile]) { seen[s[i].tile] = 1; out.push(s[i]); }
    return out;
  }

  /* ---------------- credit ---------------- */
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function niceDate(d) { return MON[+d.slice(5, 7) - 1] + ' ' + (+d.slice(8, 10)) + ', ' + d.slice(0, 4); }

  function credit(granules) {
    granules = granules || [];
    var dates = {}, years = {}, sensors = {};
    for (var i = 0; i < granules.length; i++) {
      var d = ymdOf(granules[i].time);
      dates[d] = 1; years[d.slice(0, 4)] = 1; sensors[granules[i].sensor.replace('S1', 'Sentinel-1')] = 1;
    }
    var dl = Object.keys(dates).sort().reverse().map(niceDate);
    var yl = Object.keys(years).sort();
    if (!yl.length) yl = [String(new Date().getUTCFullYear())];
    var sl = Object.keys(sensors).sort();
    return 'Radar-seen water: <a href="' + DATASET_URL + '" target="_blank" rel="noopener">NASA/JPL OPERA DSWx-S1</a>' +
      (dl.length ? ', ' + (dl.length > 1 ? 'passes ' : 'pass ') + dl.join(', ') : '') +
      (sl.length ? ' (' + sl.join(', ') + ')' : '') +
      '. Contains modified Copernicus Sentinel data ' + yl.join(', ') + '.';
  }

  /* ---------------- Leaflet layer ---------------- */
  var filterSeq = 0;
  function hexRGB(h) {
    h = String(h).replace('#', '');
    if (h.length === 3) h = h.replace(/(.)/g, '$1$1');
    return [parseInt(h.slice(0, 2), 16) / 255, parseInt(h.slice(2, 4), 16) / 255, parseInt(h.slice(4, 6), 16) / 255];
  }

  // Recolour without reading pixels (the browse PNG is cross-origin, the canvas is tainted):
  // an SVG colour matrix applied as a CSS filter on the display canvas.
  //   alpha' = A - R (white and white-blends vanish) ; with veg hidden alpha' = A - G.
  //   colour' = water*B + veg*(G - R), so blue/white edge blends stay water-coloured.
  function makeFilter(color, vegColor) {
    var id = 'bvdswx-f' + (++filterSeq);
    var w = hexRGB(color), v = vegColor ? hexRGB(vegColor) : [0, 0, 0];
    var rows = [];
    for (var c = 0; c < 3; c++) rows.push([-v[c], v[c], w[c], 0, 0].join(' '));
    rows.push(vegColor ? '-1 0 0 1 0' : '0 -1 0 1 0');
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('width', '0'); svg.setAttribute('height', '0');
    svg.setAttribute('aria-hidden', 'true');
    svg.style.position = 'absolute'; svg.style.width = '0'; svg.style.height = '0'; svg.style.overflow = 'hidden';
    var fl = document.createElementNS(ns, 'filter');
    fl.setAttribute('id', id); fl.setAttribute('color-interpolation-filters', 'sRGB');
    fl.setAttribute('x', '0'); fl.setAttribute('y', '0'); fl.setAttribute('width', '1'); fl.setAttribute('height', '1');
    var cm1 = document.createElementNS(ns, 'feColorMatrix');
    cm1.setAttribute('type', 'matrix'); cm1.setAttribute('values', rows.join('  '));
    fl.appendChild(cm1); svg.appendChild(fl);
    document.body.appendChild(svg);
    return { id: id, svg: svg };
  }

  var LayerClass = null;
  function buildClass() {
    var L = window.L;
    if (!L) throw new Error('bvDSWx.layer needs Leaflet');
    LayerClass = L.Layer.extend({
      options: { opacity: 0.85, color: '#1f6fe0', vegColor: '#2e9e62', mesh: 32, smooth: true, pad: 0.35, pane: 'overlayPane' },

      initialize: function (granules, options) {
        L.setOptions(this, options);
        this._tiles = [];
        this.setGranules(granules || []);
      },

      setGranules: function (granules) {
        var self = this;
        // draw oldest first so the newest pass sits on top
        this._tiles = granules.slice().sort(function (x, y) { return x.time - y.time; }).map(function (g) {
          var t = { g: g, img: new Image(), ready: false, mesh: self._buildMesh(g) };
          t.img.referrerPolicy = 'no-referrer';
          t.img.onload = function () { t.ready = true; if (self._map) self._redraw(); };
          t.img.onerror = function () { t.failed = true; };
          t.img.src = g.browse;
          return t;
        });
        if (this._map) this._redraw();
        return this;
      },

      _buildMesh: function (g) {
        var N = this.options.mesh, ll = [];
        for (var j = 0; j <= N; j++) for (var i = 0; i <= N; i++) ll.push(tileLatLng(g, i * IMG / N, j * IMG / N));
        var env = g.envelope;
        return { N: N, ll: ll, bounds: window.L.latLngBounds([env.south, env.west], [env.north, env.east]) };
      },

      onAdd: function (map) {
        var c = this._canvas = window.L.DomUtil.create('canvas', 'bv-dswx-layer leaflet-layer');
        c.style.pointerEvents = 'none';
        if (map._zoomAnimated) window.L.DomUtil.addClass(c, 'leaflet-zoom-animated');
        this._filter = makeFilter(this.options.color, this.options.vegColor);
        c.style.filter = 'url(#' + this._filter.id + ')';
        c.style.opacity = this.options.opacity;
        this.getPane().appendChild(c);
        this._redraw();
      },

      onRemove: function () {
        window.L.DomUtil.remove(this._canvas);
        if (this._filter) window.L.DomUtil.remove(this._filter.svg);
        this._canvas = this._filter = null;
      },

      getEvents: function () {
        var ev = { moveend: this._redraw, zoomend: this._redraw, viewreset: this._redraw, resize: this._redraw };
        if (this._map && this._map._zoomAnimated) ev.zoomanim = this._animateZoom;
        return ev;
      },

      setOpacity: function (o) {
        this.options.opacity = o;
        if (this._canvas) this._canvas.style.opacity = o;
        return this;
      },

      _animateZoom: function (ev) {
        if (!this._cbounds) return;
        var map = this._map;
        var scale = map.getZoomScale(ev.zoom);
        var off = map._latLngBoundsToNewLayerBounds(this._cbounds, ev.zoom, ev.center).min;
        window.L.DomUtil.setTransform(this._canvas, off, scale);
      },

      _redraw: function () {
        var map = this._map, c = this._canvas;
        if (!map || !c) return;
        var L = window.L, t0 = (window.performance || Date).now();
        var size = map.getSize(), pad = this.options.pad;
        var padPt = size.multiplyBy(pad).round();
        var topLeft = map.containerPointToLayerPoint(padPt.multiplyBy(-1));
        var w = size.x + 2 * padPt.x, h = size.y + 2 * padPt.y;
        var dpr = Math.min(window.devicePixelRatio || 1, 2);
        c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
        c.style.width = w + 'px'; c.style.height = h + 'px';
        L.DomUtil.setPosition(c, topLeft);
        this._cbounds = L.latLngBounds(map.layerPointToLatLng(topLeft), map.layerPointToLatLng(topLeft.add([w, h])));
        var ctx = c.getContext('2d');
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, c.width, c.height);
        ctx.imageSmoothingEnabled = !!this.options.smooth;
        var viewB = this._cbounds, drawn = 0;
        for (var k = 0; k < this._tiles.length; k++) {
          var t = this._tiles[k];
          if (!t.ready || !viewB.intersects(t.mesh.bounds)) continue;
          drawn += this._drawTile(ctx, t, topLeft, dpr, c.width, c.height);
        }
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        this.lastRender = { ms: Math.round(((window.performance || Date).now() - t0) * 10) / 10, triangles: drawn };
      },

      // Each mesh cell is split in two triangles; each triangle gets the exact affine map that
      // sends its three image vertices to their Web-Mercator screen points, is clipped
      // (inflated half a device pixel to hide seams) and draws only the cell's source rectangle.
      _drawTile: function (ctx, t, topLeft, dpr, cw, ch) {
        var map = this._map, m = t.mesh, N = m.N, step = IMG / N, pts = new Array(m.ll.length);
        for (var q = 0; q < m.ll.length; q++) {
          var p = map.latLngToLayerPoint(m.ll[q]);
          pts[q] = [(p.x - topLeft.x) * dpr, (p.y - topLeft.y) * dpr];
        }
        var count = 0, img = t.img;
        for (var j = 0; j < N; j++) {
          for (var i = 0; i < N; i++) {
            var i00 = j * (N + 1) + i, i10 = i00 + 1, i01 = i00 + N + 1, i11 = i01 + 1;
            var P00 = pts[i00], P10 = pts[i10], P01 = pts[i01], P11 = pts[i11];
            var minx = Math.min(P00[0], P10[0], P01[0], P11[0]), maxx = Math.max(P00[0], P10[0], P01[0], P11[0]);
            var miny = Math.min(P00[1], P10[1], P01[1], P11[1]), maxy = Math.max(P00[1], P10[1], P01[1], P11[1]);
            if (maxx < 0 || maxy < 0 || minx > cw || miny > ch) continue;
            var u0 = i * step, v0 = j * step, u1 = u0 + step, v1 = v0 + step;
            var sx = Math.max(0, Math.floor(u0) - 1), sy = Math.max(0, Math.floor(v0) - 1);
            var sw = Math.min(IMG, Math.ceil(u1) + 1) - sx, sh = Math.min(IMG, Math.ceil(v1) + 1) - sy;
            // triangle A: (u0,v0) (u1,v0) (u0,v1) ; triangle B: (u1,v1) (u0,v1) (u1,v0)
            drawTri(ctx, img, P00, P10, P01, u0, v0, step, step, sx, sy, sw, sh);
            drawTri(ctx, img, P11, P01, P10, u1, v1, -step, -step, sx, sy, sw, sh);
            count += 2;
          }
        }
        return count;
      }
    });
  }

  // pa = image (ua, va); pb = image (ua + du, va); pc = image (ua, va + dv)
  function drawTri(ctx, img, pa, pb, pc, ua, va, du, dv, sx, sy, sw, sh) {
    var a1 = (pb[0] - pa[0]) / du, b1 = (pb[1] - pa[1]) / du;   // screen per +u
    var c1 = (pc[0] - pa[0]) / dv, d1 = (pc[1] - pa[1]) / dv;   // screen per +v
    var e1 = pa[0] - a1 * ua - c1 * va, f1 = pa[1] - b1 * ua - d1 * va;
    var cx = (pa[0] + pb[0] + pc[0]) / 3, cy = (pa[1] + pb[1] + pc[1]) / 3;
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.beginPath();
    var tri = [pa, pb, pc];
    for (var k = 0; k < 3; k++) {
      var dx = tri[k][0] - cx, dy = tri[k][1] - cy, len = Math.sqrt(dx * dx + dy * dy) || 1;
      var x = tri[k][0] + dx / len * 0.7, y = tri[k][1] + dy / len * 0.7;
      if (k) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    }
    ctx.closePath();
    ctx.clip();
    ctx.setTransform(a1, b1, c1, d1, e1, f1);
    ctx.drawImage(img, sx, sy, sw, sh, sx, sy, sw, sh);
    ctx.restore();
  }

  function layer(granules, opts) {
    if (!LayerClass) buildClass();
    return new LayerClass(granules, opts);
  }

  window.bvDSWx = {
    find: find, latestPass: latestPass, groupPasses: groupPasses, newestPerTile: newestPerTile,
    layer: layer, credit: credit, tileCorners: tileCorners, pixelLatLng: pixelLatLng,
    utm: { forward: utmForward, inverse: utmInverse },
    _geom: { fitCorner: fitCorner, squareEnvelope: squareEnvelope, TILE_M: TILE_M, IMG: IMG, S: S },
    DATASET_URL: DATASET_URL
  };
})();
