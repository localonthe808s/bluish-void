/*
 * level3.js -- NEXRAD Level III (RPG product) decoder + canvas renderer.
 * window.bvL3.  Plain ES5, no build step. Needs window.bvBunzip (bunzip.js)
 * for the bzip2-compressed digital products.
 *
 * Source: Unidata's public mirror of the NWS Level III feed on AWS
 *   https://unidata-nexrad-level3.s3.amazonaws.com/  (CORS-open, public domain)
 *   keys: SSS_PPP_YYYY_MM_DD_HH_MM_SS  e.g. OKX_N0C_2026_09_23_23_56_55
 *
 * Format: NWS ICD 2620001 (RPG to Class 1 User). File = 30-byte WMO header,
 * 18-byte message header, 102-byte product description block (PDB), then the
 * symbology block -- bzip2-compressed from byte 120 of the message when PDB
 * halfword dep8 == 1. Radial data is packet 16 (digital radial data array,
 * one byte per gate) or packet 0xAF1F (legacy run-length radial).
 *
 * API
 *   bvL3.latest(site, product)      -> Promise {key, time: Date, url}
 *   bvL3.list(site, product, date)  -> Promise [{key, time, url, size}]
 *   bvL3.load(url | ArrayBuffer)    -> Promise decoded (see parse)
 *   bvL3.parse(Uint8Array)          -> decoded:
 *       {site, product, code, name, units, lat, lon, heightFt, time: Date,
 *        elevation (deg), radials:[{az, width}], gates:{first, size, n}
 *        (km; gate i spans first+i*size .. +size of slant range),
 *        values: Float32Array[radial*n] physical units, NaN = no data,
 *        codes: Uint8Array raw levels, lut: Float32Array(256) code->value,
 *        bytes:{file, uncompressed}, timing:{fetch, bunzip, parse} ms, meta}
 *   bvL3.gateLatLon(d, radialIdx, gateIdx) -> [lat, lon] of the gate centre
 *   bvL3.bounds(d)                  -> [[south, west], [north, east]]
 *   bvL3.toCanvas(d, projectFn, opts) -> {canvas, ms, pixels}
 *       projectFn(lat, lon) -> [x, y] or {x, y} in canvas pixels.
 *       opts: canvas | width+height, scale (fn(v)->[r,g,b,a] or name),
 *             opacity (0..1), gridKm (projection sample spacing, default auto),
 *             maxRangeKm, clear (default true)
 *   bvL3.scales.{cc, zdr, kdp, vil, ref, vel}(v) -> [r,g,b,a] | null
 *   bvL3.legend(product) -> HTML string
 */
(function (root) {
  'use strict';

  var BUCKET = 'https://unidata-nexrad-level3.s3.amazonaws.com/';
  var RE_KM = 6371.0, KE_RE = RE_KM * 4 / 3;
  var D2R = Math.PI / 180;

  // ---------------------------------------------------------------- products
  // gateKm: gate spacing; rangeKm: nominal max range; map: level decoding.
  var PRODUCTS = {
    94:  { id: 'N0Q', name: 'Digital Base Reflectivity', units: 'dBZ', gateKm: 1, rangeKm: 460, map: 'dig', scale: 'ref' },
    99:  { id: 'N0U', name: 'Digital Base Velocity', units: 'm/s', gateKm: 0.25, rangeKm: 300, map: 'dig', scale: 'vel' },
    134: { id: 'DVL', name: 'Digital Vertically Integrated Liquid', units: 'kg/m²', gateKm: 1, rangeKm: 460, map: 'vil', scale: 'vil' },
    153: { id: 'N0B', name: 'Super-Res Base Reflectivity', units: 'dBZ', gateKm: 0.25, rangeKm: 460, map: 'dig', scale: 'ref' },
    154: { id: 'N0G', name: 'Super-Res Base Velocity', units: 'm/s', gateKm: 0.25, rangeKm: 300, map: 'dig', scale: 'vel' },
    159: { id: 'N0X', name: 'Differential Reflectivity', units: 'dB', gateKm: 0.25, rangeKm: 300, map: 'generic', scale: 'zdr' },
    161: { id: 'N0C', name: 'Correlation Coefficient', units: '', gateKm: 0.25, rangeKm: 300, map: 'generic', scale: 'cc' },
    163: { id: 'N0K', name: 'Specific Differential Phase', units: 'deg/km', gateKm: 0.25, rangeKm: 300, map: 'generic', scale: 'kdp' }
  };
  var BY_ID = {};
  (function () { for (var c in PRODUCTS) BY_ID[PRODUCTS[c].id] = +c; })();

  // ---------------------------------------------------------------- helpers
  function i16(u, o) { var v = (u[o] << 8) | u[o + 1]; return v & 0x8000 ? v - 0x10000 : v; }
  function u16(u, o) { return (u[o] << 8) | u[o + 1]; }
  function i32(u, o) { return (u[o] << 24) | (u[o + 1] << 16) | (u[o + 2] << 8) | u[o + 3]; }
  function u32(u, o) { return i32(u, o) >>> 0; }
  var _f32 = new DataView(new ArrayBuffer(4));
  function f32(hi, lo) { _f32.setUint16(0, hi & 0xffff); _f32.setUint16(2, lo & 0xffff); return _f32.getFloat32(0); }
  // ICD custom 16-bit float (sign 1, exponent 5, fraction 10; bias 16)
  function f16(v) {
    v &= 0xffff;
    var frac = v & 0x3ff, exp = (v >> 10) & 0x1f, s = v >> 15;
    var x = exp ? Math.pow(2, exp - 16) * (1 + frac / 1024) : frac / 512;
    return s ? -x : x;
  }
  function now() { return (root.performance && performance.now) ? performance.now() : Date.now(); }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function ymd(d) { return d.getUTCFullYear() + '_' + pad2(d.getUTCMonth() + 1) + '_' + pad2(d.getUTCDate()); }
  function normSite(s) { s = String(s).toUpperCase(); return (s.length === 4 && s.charAt(0) === 'K') ? s.slice(1) : s; }
  function normProd(p) { return typeof p === 'number' ? (PRODUCTS[p] ? PRODUCTS[p].id : String(p)) : String(p).toUpperCase(); }
  function keyTime(k) {
    var m = /_(\d{4})_(\d\d)_(\d\d)_(\d\d)_(\d\d)_(\d\d)$/.exec(k);
    return m ? new Date(Date.UTC(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +m[6])) : null;
  }

  // ---------------------------------------------------------------- listing
  function list(site, product, date) {
    var prefix = normSite(site) + '_' + normProd(product) + '_' + ymd(date || new Date());
    var out = [];
    function page(token) {
      var u = BUCKET + '?list-type=2&prefix=' + encodeURIComponent(prefix) +
        (token ? '&continuation-token=' + encodeURIComponent(token) : '');
      return fetch(u).then(function (r) {
        if (!r.ok) throw new Error('bvL3 list HTTP ' + r.status);
        return r.text();
      }).then(function (x) {
        var re = /<Key>([^<]+)<\/Key>[\s\S]*?<Size>(\d+)<\/Size>/g, m;
        while ((m = re.exec(x))) out.push({ key: m[1], time: keyTime(m[1]), url: BUCKET + m[1], size: +m[2] });
        var t = /<IsTruncated>true<\/IsTruncated>/.test(x) && /<NextContinuationToken>([^<]+)</.exec(x);
        return t ? page(t[1]) : out;
      });
    }
    return page(null);
  }

  function latest(site, product) {
    var today = new Date();
    return list(site, product, today).then(function (a) {
      if (a.length) return a;
      return list(site, product, new Date(today.getTime() - 86400000));
    }).then(function (a) {
      if (!a.length) throw new Error('bvL3: no ' + normSite(site) + ' ' + normProd(product) + ' files today or yesterday');
      var k = a[a.length - 1];
      return { key: k.key, time: k.time, url: k.url, size: k.size };
    });
  }

  // ---------------------------------------------------------------- decoding
  function findMessage(u) {
    // WMO/AWIPS text header of variable length precedes the message; locate
    // the message header by its PDB divider (-1) and matching product code.
    for (var o = 0; o < Math.min(u.length - 140, 300); o++) {
      if (i16(u, o + 18) === -1 && u16(u, o) === i16(u, o + 30) && u16(u, o) > 15 && u16(u, o) < 400) return o;
    }
    throw new Error('bvL3: no Level III message header found');
  }

  function buildLut(p, thr) {
    var lut = new Float32Array(256), i;
    for (i = 0; i < 256; i++) lut[i] = NaN;
    var map = p ? p.map : 'dig';
    if (map === 'generic') {
      var scale = f32(thr[0], thr[1]), off = f32(thr[2], thr[3]);
      var maxv = thr[5] & 0xffff, lead = thr[6], trail = thr[7];
      for (i = lead; i <= Math.min(255, maxv - trail); i++) lut[i] = (i - off) / scale;
    } else if (map === 'vil') {
      var ls = f16(thr[0]), lo = f16(thr[1]), start = thr[2], gs = f16(thr[3]), go = f16(thr[4]);
      for (i = 2; i < start; i++) lut[i] = (i - lo) / ls;
      for (i = start; i < 255; i++) lut[i] = Math.exp((i - go) / gs);
    } else { // 'dig': min (0.1 units), increment (0.1 units), level count
      var mn = thr[0] * 0.1, inc = thr[1] * 0.1, nl = Math.min(thr[2], 254);
      for (i = 0; i < nl; i++) lut[i + 2] = mn + i * inc;
    }
    lut[0] = NaN; lut[1] = NaN;                 // below threshold / range folded
    return lut;
  }

  function parse(input, fileBytes) {
    var t0 = now();
    var u = input instanceof Uint8Array ? input : new Uint8Array(input);
    var ms = findMessage(u), P = ms + 18;
    var code = u16(u, ms);
    var p = PRODUCTS[code] || null;
    var thr = [], dep = [], i;
    for (i = 0; i < 16; i++) thr.push(i16(u, P + 42 + 2 * i));
    dep.push(i16(u, P + 34), i16(u, P + 36), i16(u, P + 40));
    for (i = 0; i < 7; i++) dep.push(i16(u, P + 74 + 2 * i));
    var volDate = u16(u, P + 22), volSec = u32(u, P + 24);
    var meta = {
      msgCode: code, vcp: i16(u, P + 16), opMode: i16(u, P + 14), elNum: i16(u, P + 38),
      volNum: i16(u, P + 20), version: u[P + 88], thresholds: thr, dependent: dep,
      productTime: new Date((u16(u, P + 28) - 1) * 86400000 + u32(u, P + 30) * 1000)
    };
    var header = u.subarray(0, ms).length ? String.fromCharCode.apply(null, u.subarray(0, Math.min(ms, 40))) : '';
    var mSite = /\n[A-Z0-9]{3}([A-Z0-9]{3})\r*\n/.exec(header);
    var symOff = u32(u, P + 90) * 2;

    // bzip2 symbology
    var msg = u.subarray(ms), unc = msg.length, tb = 0;
    var comp = dep[7];
    if (comp === 1) {
      if (!root.bvBunzip) throw new Error('bvL3: bunzip.js not loaded');
      var tb0 = now();
      var body = root.bvBunzip(msg.subarray(120));
      var m2 = new Uint8Array(120 + body.length);
      m2.set(msg.subarray(0, 120)); m2.set(body, 120);
      msg = m2; unc = m2.length; tb = now() - tb0;
    } else if (comp) {
      throw new Error('bvL3: unknown compression ' + comp);
    }

    // symbology block -> layers -> packets
    var o = symOff;
    if (i16(msg, o) !== -1 || i16(msg, o + 2) !== 1) throw new Error('bvL3: bad symbology block');
    var nLayer = u16(msg, o + 8); o += 10;
    var packets = [], radial = null;
    for (var L = 0; L < nLayer; L++) {
      var lLen = u32(msg, o + 2); o += 6;
      var lEnd = o + lLen;
      while (o < lEnd) {
        var pc = u16(msg, o);
        packets.push(pc);
        if (pc === 16 || pc === 0xAF1F) {
          var first = u16(msg, o + 2), nb = u16(msg, o + 4), nr = u16(msg, o + 12);
          o += 14;
          var codes = new Uint8Array(nr * nb), rads = new Array(nr);
          for (var r = 0; r < nr; r++) {
            var cnt = u16(msg, o), sa = i16(msg, o + 2) * 0.1, da = i16(msg, o + 4) * 0.1;
            o += 6;
            rads[r] = { az: sa, width: da };
            var base = r * nb;
            if (pc === 16) {
              var k = Math.min(cnt, nb);
              codes.set(msg.subarray(o, o + k), base);
              o += cnt + (cnt & 1);
            } else {                         // RLE: count halfwords, 4-bit run / 4-bit colour
              var g = 0;
              for (var b = 0; b < cnt * 2; b++) {
                var byte = msg[o + b], run = byte >> 4, col = byte & 15;
                for (var q = 0; q < run && g < nb; q++) codes[base + g++] = col;
              }
              o += cnt * 2;
            }
          }
          if (!radial) radial = { first: first, nb: nb, nr: nr, codes: codes, rads: rads, packet: pc };
        } else {
          o = lEnd;                            // other packets: skip rest of layer
        }
      }
      o = lEnd;
    }
    if (!radial) throw new Error('bvL3: no radial packet (packets: ' + packets.join(',') + ')');

    var lut = buildLut(p, thr);
    var n = radial.nb, vals = new Float32Array(radial.nr * n), cs = radial.codes;
    for (i = 0; i < vals.length; i++) vals[i] = lut[cs[i]];

    var gateKm = p ? p.gateKm : (n > 500 ? 0.25 : 1);
    var t1 = now();
    return {
      site: mSite ? mSite[1] : '',
      product: p ? p.id : String(code), code: code,
      name: p ? p.name : 'Product ' + code, units: p ? p.units : '',
      scale: p ? p.scale : null,
      lat: i32(u, P + 2) * 0.001, lon: i32(u, P + 6) * 0.001, heightFt: i16(u, P + 10),
      time: new Date((volDate - 1) * 86400000 + volSec * 1000),
      elevation: code === 134 ? 0 : dep[2] * 0.1,
      radials: radial.rads,
      gates: { first: radial.first * gateKm, size: gateKm, n: n },
      values: vals, codes: cs, lut: lut,
      packets: packets, packet: radial.packet,
      bytes: { file: fileBytes || u.length, uncompressed: unc, compressed: comp === 1 },
      timing: { bunzip: tb, parse: (t1 - t0) - tb, total: t1 - t0 },
      meta: meta
    };
  }

  function load(src) {
    var t0 = now();
    var pr = typeof src === 'string'
      ? fetch(src.indexOf('://') < 0 ? BUCKET + src : src).then(function (r) {
          if (!r.ok) throw new Error('bvL3 fetch HTTP ' + r.status);
          return r.arrayBuffer();
        })
      : Promise.resolve(src);
    return pr.then(function (buf) {
      var tf = now() - t0;
      var d = parse(new Uint8Array(buf), buf.byteLength);
      d.timing.fetch = tf;
      d.url = typeof src === 'string' ? src : null;
      var mk = d.url && /([A-Z0-9]{3})_[A-Z0-9]{3}_\d{4}_/.exec(d.url);
      if (!d.site && mk) d.site = mk[1];
      return d;
    });
  }

  // ---------------------------------------------------------------- geometry
  // 4/3-earth beam: slant range r (km), elevation (deg) -> ground range (km)
  function groundRange(r, elDeg) {
    var e = elDeg * D2R, R = KE_RE;
    var h = Math.sqrt(r * r + R * R + 2 * r * R * Math.sin(e)) - R;
    return R * Math.asin(r * Math.cos(e) / (R + h));
  }
  function beamHeight(r, elDeg) {
    var e = elDeg * D2R, R = KE_RE;
    return Math.sqrt(r * r + R * R + 2 * r * R * Math.sin(e)) - R;
  }
  // great-circle destination from (lat, lon), bearing (deg), distance (km)
  function dest(lat, lon, brg, km) {
    var p1 = lat * D2R, l1 = lon * D2R, t = brg * D2R, d = km / RE_KM;
    var sp = Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(t);
    var p2 = Math.asin(sp);
    var l2 = l1 + Math.atan2(Math.sin(t) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * sp);
    return [p2 / D2R, ((l2 / D2R + 540) % 360) - 180];
  }
  function gateLatLon(d, ri, gi) {
    var rad = d.radials[ri];
    var r = d.gates.first + (gi + 0.5) * d.gates.size;
    return dest(d.lat, d.lon, rad.az + rad.width / 2, groundRange(r, d.elevation));
  }
  function maxGround(d) { return groundRange(d.gates.first + d.gates.n * d.gates.size, d.elevation); }
  function bounds(d, maxKm) {
    var s = maxKm || maxGround(d);
    var n = dest(d.lat, d.lon, 0, s)[0], so = dest(d.lat, d.lon, 180, s)[0];
    var dLon = s / (RE_KM * Math.cos(Math.max(Math.abs(n), Math.abs(so)) * D2R)) / D2R;
    return [[so, d.lon - dLon], [n, d.lon + dLon]];
  }

  // ---------------------------------------------------------------- scales
  function hex(h) { return [parseInt(h.substr(1, 2), 16), parseInt(h.substr(3, 2), 16), parseInt(h.substr(5, 2), 16)]; }
  // stops: [[value, '#rrggbb', alpha?], ...]; equal values make a hard break
  function ramp(stops, opt) {
    opt = opt || {};
    var S = stops.map(function (s) { var c = hex(s[1]); c.push(s.length > 2 ? s[2] : 1); return [s[0], c]; });
    var f = function (v) {
      if (v !== v) return null;
      if (opt.min != null && v < opt.min) return null;
      if (v <= S[0][0]) return S[0][1].slice();
      for (var i = 1; i < S.length; i++) {
        if (v < S[i][0] || (i === S.length - 1)) {
          var a = S[i - 1], b = S[i];
          if (v >= b[0]) return b[1].slice();
          if (opt.step) return a[1].slice();
          var t = (v - a[0]) / (b[0] - a[0] || 1);
          return [Math.round(a[1][0] + t * (b[1][0] - a[1][0])), Math.round(a[1][1] + t * (b[1][1] - a[1][1])),
                  Math.round(a[1][2] + t * (b[1][2] - a[1][2])), a[1][3] + t * (b[1][3] - a[1][3])];
        }
      }
      return S[S.length - 1][1].slice();
    };
    f.stops = stops; f.step = !!opt.step; f.min = opt.min;
    return f;
  }

  var scales = {
    // CC: >=0.97 blue/grey = uniform rain or snow; 0.90-0.97 yellow = mixed /
    // melting layer / big drops; <0.90 orange->red->magenta = non-met
    // (debris, birds, bugs, ground clutter) or large hail.
    cc: ramp([
      [0.20, '#d63ec8'], [0.45, '#c42a8c'], [0.65, '#c81e32'], [0.80, '#e8482a'],
      [0.90, '#f5961e'], [0.90, '#e8c21e'], [0.97, '#f2ec8c'],
      [0.97, '#a8cbe8'], [0.995, '#6f93c6'], [1.05, '#8f99a8']
    ], { min: 0.2 }),
    // ZDR (dB): negative greys, ~0 light grey, then blue, green, yellow,
    // orange, red, pink, white for big drops / hail.
    zdr: ramp([
      [-4, '#3a3a3a'], [-1, '#8c8c8c'], [0, '#d0d0d0'], [0, '#a6d4f2'], [1, '#2f7fd8'],
      [1, '#48c864'], [2, '#1d8f35'], [2, '#f0e24c'], [3, '#f0a628'], [3, '#ee7424'],
      [4, '#d82626'], [5, '#9a1414'], [5, '#f28cc8'], [6, '#d44cac'], [6, '#ffffff'], [8, '#ffffff']
    ]),
    // KDP (deg/km): near zero faint grey (shown translucent), >1 heavy rain
    kdp: ramp([
      [-2, '#5a5a5a', 0.5], [-0.5, '#9a9a9a', 0.4], [0, '#c8c8c8', 0.3], [0.5, '#9ccbee', 0.7],
      [1, '#3c8ce6'], [1.5, '#3cc864'], [2, '#1e9632'], [3, '#f0e24c'], [4, '#f09628'],
      [5, '#dc2828'], [6, '#9a1414'], [7, '#e650c8'], [10, '#ffffff']
    ]),
    // VIL (kg/m2), NWS DVL-like
    vil: ramp([
      [0.1, '#9cb4c8', 0.5], [1, '#78b4e6', 0.8], [5, '#28a0dc'], [10, '#1ec85a'], [15, '#14962d'],
      [20, '#f0e650'], [25, '#f0b428'], [30, '#f07828'], [40, '#dc2828'], [50, '#a01414'],
      [60, '#e650c8'], [70, '#ffffff'], [80, '#ffffff']
    ], { min: 0.1 }),
    // Reflectivity (dBZ), NWS stepped palette
    ref: ramp([
      [5, '#04e9e7'], [10, '#019ff4'], [15, '#0300f4'], [20, '#02fd02'], [25, '#01c501'],
      [30, '#008e00'], [35, '#fdf802'], [40, '#e5bc00'], [45, '#fd9500'], [50, '#fd0000'],
      [55, '#d40000'], [60, '#bc0000'], [65, '#f800fd'], [70, '#9854c6'], [75, '#fdfdfd'], [95, '#fdfdfd']
    ], { step: true, min: 5 }),
    // Velocity (m/s): inbound green, outbound red
    vel: ramp([
      [-40, '#00ff90'], [-20, '#00b050'], [-3, '#2c5a3a'], [-0.5, '#777777'], [0.5, '#777777'],
      [3, '#5a2c2c'], [20, '#c02020'], [40, '#ff7070']
    ])
  };

  var LEGEND_TICKS = {
    cc: [0.2, 0.5, 0.8, 0.9, 0.97, 1.05],
    zdr: [-4, -1, 0, 1, 2, 3, 4, 5, 6, 8],
    kdp: [-2, 0, 1, 2, 3, 4, 5, 6, 10],
    vil: [0.1, 5, 10, 20, 30, 40, 50, 70],
    ref: [5, 15, 25, 35, 45, 55, 65, 75],
    vel: [-40, -20, 0, 20, 40]
  };
  // legend axis warp: piecewise [value, fraction]; default linear
  var LEGEND_AXIS = {
    cc: [[0.2, 0], [0.8, 0.36], [0.9, 0.56], [0.97, 0.8], [1.05, 1]],
    kdp: [[-2, 0], [0, 0.12], [6, 0.88], [10, 1]],
    vil: [[0.1, 0], [10, 0.25], [70, 1]]
  };
  function axisPos(k, v, lo, hi) {
    var a = LEGEND_AXIS[k];
    if (!a) return (v - lo) / (hi - lo);
    for (var i = 1; i < a.length; i++) if (v <= a[i][0] || i === a.length - 1)
      return a[i - 1][1] + (v - a[i - 1][0]) / (a[i][0] - a[i - 1][0]) * (a[i][1] - a[i - 1][1]);
    return 1;
  }
  var LEGEND_NOTE = {
    cc: '0.97+ uniform rain/snow · 0.90–0.97 mixed/melting · <0.90 non-weather: debris, hail, birds, clutter',
    zdr: 'drop shape: ~0 hail/snow/tumbling · 2–4 big drops · negative vertically-oriented ice or artefact',
    kdp: 'liquid water along the beam: >1 heavy rain, >3 torrential; ~0 where snow or hail dominates',
    vil: 'column liquid water; high VIL = deep cores, large hail potential',
    ref: 'returned power', vel: 'toward radar green, away red'
  };

  function scaleKey(product) {
    if (typeof product === 'number') return PRODUCTS[product] ? PRODUCTS[product].scale : null;
    var s = String(product).toLowerCase();
    if (scales[s]) return s;
    var c = BY_ID[String(product).toUpperCase()];
    return c ? PRODUCTS[c].scale : null;
  }

  function legend(product) {
    var k = scaleKey(product);
    if (!k) return '';
    var f = scales[k], st = f.stops, lo = st[0][0], hi = st[st.length - 1][0], parts = [];
    function css(s) { var c = hex(s[1]); return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + (s.length > 2 ? s[2] : 1) + ')'; }
    function at(v) { return (axisPos(k, v, lo, hi) * 100).toFixed(2) + '%'; }
    for (var i = 0; i < st.length; i++) {
      if (f.step) { if (i < st.length - 1) parts.push(css(st[i]) + ' ' + at(st[i][0]), css(st[i]) + ' ' + at(st[i + 1][0])); }
      else parts.push(css(st[i]) + ' ' + at(st[i][0]));
    }
    var code = BY_ID[String(product).toUpperCase()] || (typeof product === 'number' ? product : null);
    var p = code ? PRODUCTS[code] : null;
    var ticks = LEGEND_TICKS[k].map(function (v) {
      var pct = axisPos(k, v, lo, hi) * 100;
      return '<span style="position:absolute;left:' + pct.toFixed(2) + '%;transform:translateX(-50%)">' + v + '</span>';
    }).join('');
    return '<div class="bvl3-legend" style="font:11px/1.3 ui-monospace,Menlo,monospace;color:inherit;min-width:220px">' +
      '<div style="display:flex;justify-content:space-between;gap:10px;margin-bottom:3px"><b>' +
      (p ? p.id + ' · ' + p.name : k.toUpperCase()) + '</b><span>' + (p ? p.units : '') + '</span></div>' +
      '<div style="height:10px;border-radius:2px;background:linear-gradient(to right,' + parts.filter(Boolean).join(',') + ')"></div>' +
      '<div style="position:relative;height:14px;margin:2px 6px 0">' + ticks + '</div>' +
      '<div style="opacity:.75;margin-top:2px">' + LEGEND_NOTE[k] + '</div></div>';
  }

  // ---------------------------------------------------------------- render
  // Samples projectFn on a local (east, north) km grid around the radar and
  // rasterises each grid triangle, interpolating (e, n) per pixel -> (azimuth,
  // ground range) -> (radial, gate) -> colour. Forward projection only, any
  // smooth projection (Leaflet mercator, THE CITY's own) works.
  function toCanvas(d, projectFn, opts) {
    opts = opts || {};
    var t0 = now();
    var cv = opts.canvas;
    if (!cv) {
      cv = document.createElement('canvas');
      cv.width = opts.width || 512; cv.height = opts.height || 512;
    }
    var W = cv.width, H = cv.height, ctx = cv.getContext('2d');
    var img = (opts.clear === false) ? ctx.getImageData(0, 0, W, H) : ctx.createImageData(W, H);
    var px = new Uint32Array(img.data.buffer);

    // colour per raw level
    var sc = typeof opts.scale === 'function' ? opts.scale : scales[opts.scale || d.scale || scaleKey(d.code)] || scales.ref;
    var op = opts.opacity == null ? 1 : opts.opacity, colLut = new Uint32Array(256);
    for (var c = 0; c < 256; c++) {
      var rgba = sc(d.lut[c]);
      if (!rgba) continue;
      var a = Math.round(255 * op * (rgba.length > 3 ? rgba[3] : 1));
      if (a <= 0) continue;
      colLut[c] = ((a << 24) | (rgba[2] << 16) | (rgba[1] << 8) | rgba[0]) >>> 0; // little-endian RGBA
    }

    // azimuth (0.1 deg) -> radial index
    var azLut = new Int16Array(3600), ri, j;
    for (j = 0; j < 3600; j++) azLut[j] = -1;
    for (ri = 0; ri < d.radials.length; ri++) {
      var rr = d.radials[ri], a0 = Math.round(rr.az * 10), a1 = Math.round((rr.az + rr.width) * 10);
      for (j = a0; j < a1; j++) azLut[((j % 3600) + 3600) % 3600] = ri;
    }
    // ground range -> gate index
    var n = d.gates.n, g0 = d.gates.first, gs = d.gates.size, el = d.elevation;
    var sMax = Math.min(opts.maxRangeKm || 1e9, maxGround(d));
    var step = gs / 8, sLut = new Int32Array(Math.ceil(sMax / step) + 2), gi = 0;
    var edge = groundRange(g0 + gs, el);
    for (j = 0; j < sLut.length; j++) {
      var sv = (j + 0.5) * step;
      while (gi < n - 1 && sv >= edge) { gi++; edge = groundRange(g0 + (gi + 1) * gs, el); }
      sLut[j] = sv < groundRange(g0, el) ? -1 : gi;
    }

    // projection grid
    var gk = opts.gridKm || Math.max(1, sMax / 60), N = Math.ceil(sMax / gk), M = 2 * N + 1;
    var gx = new Float64Array(M * M), gy = new Float64Array(M * M), ge = new Float64Array(M * M), gn = new Float64Array(M * M);
    for (var iy = 0; iy < M; iy++) for (var ix = 0; ix < M; ix++) {
      var e = (ix - N) * gk, no = (N - iy) * gk, k = iy * M + ix;
      var s = Math.sqrt(e * e + no * no);
      var ll = s ? dest(d.lat, d.lon, Math.atan2(e, no) / D2R, s) : [d.lat, d.lon];
      var pt = projectFn(ll[0], ll[1]);
      gx[k] = pt.x != null ? pt.x : pt[0]; gy[k] = pt.y != null ? pt.y : pt[1];
      ge[k] = e; gn[k] = no;
    }

    var codes = d.codes, filled = 0, sMax2 = sMax * sMax, invStep = 1 / step, R2D = 180 / Math.PI;
    function tri(A, B, C) {
      var x0 = gx[A], y0 = gy[A], x1 = gx[B], y1 = gy[B], x2 = gx[C], y2 = gy[C];
      var minX = Math.max(0, Math.floor(Math.min(x0, x1, x2))), maxX = Math.min(W - 1, Math.ceil(Math.max(x0, x1, x2)));
      var minY = Math.max(0, Math.floor(Math.min(y0, y1, y2))), maxY = Math.min(H - 1, Math.ceil(Math.max(y0, y1, y2)));
      if (minX > maxX || minY > maxY) return;
      var den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2);
      if (Math.abs(den) < 1e-9) return;
      var inv = 1 / den, eps = -1e-7;
      var e0 = ge[A], e1 = ge[B], e2 = ge[C], n0 = gn[A], n1 = gn[B], n2 = gn[C];
      for (var y = minY; y <= maxY; y++) {
        var py = y + 0.5, row = y * W;
        for (var x = minX; x <= maxX; x++) {
          var pxc = x + 0.5;
          var w0 = ((y1 - y2) * (pxc - x2) + (x2 - x1) * (py - y2)) * inv;
          if (w0 < eps) continue;
          var w1 = ((y2 - y0) * (pxc - x2) + (x0 - x2) * (py - y2)) * inv;
          if (w1 < eps) continue;
          var w2 = 1 - w0 - w1;
          if (w2 < eps) continue;
          var ee = w0 * e0 + w1 * e1 + w2 * e2, nn = w0 * n0 + w1 * n1 + w2 * n2;
          var s2 = ee * ee + nn * nn;
          if (s2 >= sMax2) continue;
          var gIdx = sLut[(Math.sqrt(s2) * invStep) | 0];
          if (gIdx < 0) continue;
          var az = Math.atan2(ee, nn) * R2D; if (az < 0) az += 360;
          var ai = (az * 10) | 0; if (ai >= 3600) ai = 3599;
          var r = azLut[ai];
          if (r < 0) continue;
          var col = colLut[codes[r * n + gIdx]];
          if (col) { px[row + x] = col; filled++; }
        }
      }
    }
    for (iy = 0; iy < M - 1; iy++) for (ix = 0; ix < M - 1; ix++) {
      var k00 = iy * M + ix, k10 = k00 + 1, k01 = k00 + M, k11 = k01 + 1;
      tri(k00, k10, k11); tri(k00, k11, k01);
    }
    ctx.putImageData(img, 0, 0);
    return { canvas: cv, ms: now() - t0, pixels: filled };
  }

  // ---------------------------------------------------------------- stats
  function histogram(d, bins, lo, hi) {
    var v = d.values, h = new Array(bins), nan = 0, i;
    for (i = 0; i < bins; i++) h[i] = 0;
    for (i = 0; i < v.length; i++) {
      var x = v[i];
      if (x !== x) { nan++; continue; }
      var b = Math.floor((x - lo) / (hi - lo) * bins);
      h[b < 0 ? 0 : b >= bins ? bins - 1 : b]++;
    }
    return { counts: h, nan: nan, valid: v.length - nan, lo: lo, hi: hi };
  }

  root.bvL3 = {
    BUCKET: BUCKET, PRODUCTS: PRODUCTS,
    list: list, latest: latest, load: load, parse: parse,
    gateLatLon: gateLatLon, groundRange: groundRange, beamHeight: beamHeight, dest: dest,
    bounds: bounds, toCanvas: toCanvas, scales: scales, legend: legend, histogram: histogram,
    ramp: ramp
  };
})(typeof window !== 'undefined' ? window : this);
