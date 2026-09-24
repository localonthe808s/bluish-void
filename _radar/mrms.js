/* bvMRMS -- standalone NOAA MRMS GRIB2 (template 5.41, PNG packing) decoder + renderer.
 *
 * Source: NOAA MRMS public bucket (public domain, CORS-open)
 *   https://noaa-mrms-pds.s3.amazonaws.com/CONUS/<PRODUCT>/YYYYMMDD/MRMS_<PRODUCT>_YYYYMMDD-HHMMSS.grib2.gz
 *
 * API (all on window.bvMRMS):
 *   latest(product)                -> Promise {key, time, url, product}
 *   load(url | ArrayBuffer, opts)  -> Promise grid
 *       opts.bbox     [[s,w],[n,e]]  crop while decoding (rows outside are unfiltered but never stored)
 *       opts.stride   n              max-pool n x n blocks (keeps hail cores / rotation peaks)
 *       opts.maxCells default 25e6   auto-stride when the (cropped) grid is bigger than this
 *     grid = {nx, ny, lat1, lon1, dlat, dlon, time, values: Float32Array (row-major, north row first),
 *             units, param, missing: {missing, noCoverage}, stride, source: {...}, timing: {...}}
 *     lat1/lon1 are the centre of the NW cell; rows step SOUTH by dlat, columns step EAST by dlon.
 *     RotationTrack values are converted from the file's 0.001/s to s^-1.
 *   sample(grid, lat, lon)          -> value or null (outside the grid)
 *   maxNear(grid, lat, lon, miles)  -> {value, lat, lon, miles} (value null if nothing > 0)
 *   stats(grid)                     -> {max, maxLat, maxLon, positive, noCoverage, missing, cells}
 *   canvasOverlay(grid, bounds, colorFn, opts) -> HTMLCanvasElement (Web Mercator rows, for L.imageOverlay)
 *       opts.width (default 1024) ; each pixel shows the MAX of the cells it covers
 *   scales.mesh(mm) / scales.rotation(perSecond) -> [r,g,b,a]
 *   legend('mesh' | 'rotation')     -> small HTML string
 * Plain ES5, no dependencies. Needs DecompressionStream ('gzip' + 'deflate').
 */
(function () {
  'use strict';

  var BUCKET = 'https://noaa-mrms-pds.s3.amazonaws.com/';
  var NO_DS_MSG = 'This browser cannot decompress MRMS data (DecompressionStream is missing). ' +
    'Update to a current Chrome, Edge, Firefox or Safari (16.4+).';

  function supported() {
    if (typeof DecompressionStream === 'undefined') return false;
    try { new DecompressionStream('deflate'); new DecompressionStream('gzip'); return true; } catch (e) { return false; }
  }

  /* MRMS GRIB2 local table (discipline 209, category 3) for the hazard products we read. */
  var PARAMS = {
    '209.3.28': { name: 'MESH', units: 'mm', missing: -1, noCoverage: -3 },
    '209.3.29': { name: 'MESHMax30min', units: 'mm', missing: -1, noCoverage: -3 },
    '209.3.30': { name: 'MESHMax60min', units: 'mm', missing: -1, noCoverage: -3 },
    '209.3.31': { name: 'MESHMax120min', units: 'mm', missing: -1, noCoverage: -3 },
    '209.3.32': { name: 'MESHMax240min', units: 'mm', missing: -1, noCoverage: -3 },
    '209.3.33': { name: 'MESHMax360min', units: 'mm', missing: -1, noCoverage: -3 },
    '209.3.34': { name: 'MESHMax1440min', units: 'mm', missing: -1, noCoverage: -3 }
  };
  // RotationTrack (0-2 km) 2..7 and RotationTrackML (3-6 km) 14..19: file units 0.001/s, 0 = missing AND no coverage.
  (function () {
    var rt = { 2: '30min', 3: '60min', 4: '120min', 5: '240min', 6: '360min', 7: '1440min' };
    for (var k in rt) {
      PARAMS['209.3.' + k] = { name: 'RotationTrack' + rt[k], units: '1/s', fileUnits: '0.001/s', factor: 0.001, missing: 0, noCoverage: 0 };
      PARAMS['209.3.' + (+k + 12)] = { name: 'RotationTrackML' + rt[k], units: '1/s', fileUnits: '0.001/s', factor: 0.001, missing: 0, noCoverage: 0 };
    }
  })();

  function now() { return (typeof performance !== 'undefined' ? performance.now() : Date.now()); }

  /* ---------------- S3 listing ---------------- */
  function ymd(d) {
    return d.getUTCFullYear() + ('0' + (d.getUTCMonth() + 1)).slice(-2) + ('0' + d.getUTCDate()).slice(-2);
  }
  function keyTime(key) {
    var m = /_(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})\.grib2/.exec(key);
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) : NaN;
  }
  function listKeys(product, day, startAfter) {
    var prefix = 'CONUS/' + product + '/' + day + '/';
    var keys = [];
    function page(token) {
      var u = BUCKET + '?list-type=2&prefix=' + encodeURIComponent(prefix);
      if (token) u += '&continuation-token=' + encodeURIComponent(token);
      else if (startAfter) u += '&start-after=' + encodeURIComponent(prefix + startAfter);
      return fetch(u, { cache: 'no-store' }).then(function (r) {
        if (!r.ok) throw new Error('MRMS listing HTTP ' + r.status);
        return r.text();
      }).then(function (xml) {
        var re = /<Key>([^<]+)<\/Key>/g, m;
        while ((m = re.exec(xml))) keys.push(m[1]);
        var t = /<NextContinuationToken>([^<]+)<\/NextContinuationToken>/.exec(xml);
        if (/<IsTruncated>true<\/IsTruncated>/.test(xml) && t) return page(t[1].replace(/&amp;/g, '&'));
        return keys;
      });
    }
    return page(null);
  }
  function latest(product) {
    var d = new Date();
    var today = ymd(d);
    var yest = ymd(new Date(d.getTime() - 86400000));
    // Skip most of today's listing: start three hours back (keys sort by time within a day).
    var h = Math.max(0, d.getUTCHours() - 3);
    var startAfter = 'MRMS_' + product + '_' + today + '-' + ('0' + h).slice(-2) + '0000';
    function pick(keys) {
      if (!keys.length) return null;
      keys.sort();
      var k = keys[keys.length - 1];
      return { key: k, time: keyTime(k), url: BUCKET + k, product: product };
    }
    return listKeys(product, today, h > 0 ? startAfter : null).then(function (keys) {
      if (keys.length) return keys;
      return h > 0 ? listKeys(product, today, null) : keys;
    }).then(function (keys) {
      var p = pick(keys);
      if (p) return p;
      return listKeys(product, yest, null).then(function (k2) {
        var p2 = pick(k2);
        if (!p2) throw new Error('No MRMS files for ' + product + ' today or yesterday');
        return p2;
      });
    });
  }

  /* ---------------- byte helpers ---------------- */
  function u16(b, p) { return (b[p] << 8) | b[p + 1]; }
  function u32(b, p) { return ((b[p] << 24) >>> 0) + (b[p + 1] << 16) + (b[p + 2] << 8) + b[p + 3]; }
  function s32sm(b, p) { var v = u32(b, p); return (v & 0x80000000) ? -(v & 0x7fffffff) : v; } // GRIB sign-magnitude
  function s16sm(b, p) { var v = u16(b, p); return (v & 0x8000) ? -(v & 0x7fff) : v; }
  function f32(b, p) { return new DataView(b.buffer, b.byteOffset + p, 4).getFloat32(0, false); }

  function streamToBytes(stream) {
    return new Response(stream).arrayBuffer().then(function (ab) { return new Uint8Array(ab); });
  }
  function gunzip(bytes) {
    if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return Promise.resolve(bytes); // already plain GRIB
    return streamToBytes(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')));
  }

  /* ---------------- GRIB2 section parse (single message) ---------------- */
  function parseGrib(b) {
    if (b[0] !== 0x47 || b[1] !== 0x52 || b[2] !== 0x49 || b[3] !== 0x42) throw new Error('Not a GRIB file');
    if (b[7] !== 2) throw new Error('Not GRIB edition 2');
    var g = { discipline: b[6] };
    var total = u32(b, 12) + u32(b, 8) * 4294967296;
    var p = 16;
    while (p < total - 4) {
      if (b[p] === 0x37 && b[p + 1] === 0x37 && b[p + 2] === 0x37 && b[p + 3] === 0x37) break;
      var len = u32(b, p), n = b[p + 4];
      if (n === 1) {
        g.time = Date.UTC(u16(b, p + 12), b[p + 14] - 1, b[p + 15], b[p + 16], b[p + 17], b[p + 18]);
      } else if (n === 3) {
        var tmpl3 = u16(b, p + 12);
        if (tmpl3 !== 0) throw new Error('Grid template 3.' + tmpl3 + ' not supported (need 3.0 lat/lon)');
        var basic = u32(b, p + 38), sub = u32(b, p + 42);
        var unit = (basic === 0 || basic === 0xffffffff || sub === 0xffffffff || sub === 0) ? 1e-6 : basic / sub;
        g.nx = u32(b, p + 30); g.ny = u32(b, p + 34);
        g.la1 = s32sm(b, p + 46) * unit; g.lo1 = s32sm(b, p + 50) * unit;
        g.la2 = s32sm(b, p + 55) * unit; g.lo2 = s32sm(b, p + 59) * unit;
        g.di = u32(b, p + 63) * unit; g.dj = u32(b, p + 67) * unit;
        g.scan = b[p + 71];
      } else if (n === 4) {
        g.category = b[p + 9]; g.number = b[p + 10];
      } else if (n === 5) {
        g.npts = u32(b, p + 5);
        g.tmpl5 = u16(b, p + 9);
        g.R = f32(b, p + 11); g.E = s16sm(b, p + 15); g.D = s16sm(b, p + 17); g.nbits = b[p + 19];
      } else if (n === 6) {
        g.bitmap = b[p + 5];
      } else if (n === 7) {
        g.data = b.subarray(p + 5, p + len);
      }
      p += len;
    }
    if (g.tmpl5 !== 41) throw new Error('Data template 5.' + g.tmpl5 + ' not supported (need 5.41 PNG)');
    if (g.bitmap !== 255) throw new Error('GRIB bitmap present; not supported');
    if (g.scan & 0x80) throw new Error('E-to-W scanning not supported');
    return g;
  }

  /* ---------------- PNG (greyscale 8/16 bit) streamed decode ---------------- */
  function pngHeader(png) {
    if (png[0] !== 0x89 || png[1] !== 0x50) throw new Error('Section 7 is not a PNG stream');
    var p = 8, hdr = null, idat = [];
    while (p < png.length) {
      var len = u32(png, p);
      var type = String.fromCharCode(png[p + 4], png[p + 5], png[p + 6], png[p + 7]);
      if (type === 'IHDR') {
        hdr = { w: u32(png, p + 8), h: u32(png, p + 12), depth: png[p + 16], color: png[p + 17], interlace: png[p + 20] };
      } else if (type === 'IDAT') {
        idat.push(png.subarray(p + 8, p + 8 + len));
      } else if (type === 'IEND') break;
      p += 12 + len;
    }
    if (!hdr) throw new Error('PNG without IHDR');
    if (hdr.color !== 0) throw new Error('PNG colour type ' + hdr.color + ' not supported (greyscale only)');
    if (hdr.depth !== 8 && hdr.depth !== 16) throw new Error('PNG bit depth ' + hdr.depth + ' not supported');
    if (hdr.interlace) throw new Error('Interlaced PNG not supported');
    hdr.idat = idat;
    return hdr;
  }

  function unfilter(ft, cur, prev, bpp, len) {
    var i;
    if (ft === 0) return;
    if (ft === 1) { for (i = bpp; i < len; i++) cur[i] = cur[i] + cur[i - bpp]; return; }
    if (ft === 2) { for (i = 0; i < len; i++) cur[i] = cur[i] + prev[i]; return; }
    if (ft === 3) {
      for (i = 0; i < bpp; i++) cur[i] = cur[i] + (prev[i] >> 1);
      for (; i < len; i++) cur[i] = cur[i] + ((cur[i - bpp] + prev[i]) >> 1);
      return;
    }
    if (ft === 4) {
      for (i = 0; i < bpp; i++) cur[i] = cur[i] + prev[i];
      for (; i < len; i++) {
        var a = cur[i - bpp], b = prev[i], c = prev[i - bpp];
        var pa = b - c, pb = a - c, pc;
        pc = pa + pb;
        if (pa < 0) pa = -pa; if (pb < 0) pb = -pb; if (pc < 0) pc = -pc;
        cur[i] = cur[i] + ((pa <= pb && pa <= pc) ? a : (pb <= pc ? b : c));
      }
      return;
    }
    throw new Error('Bad PNG filter type ' + ft);
  }

  /* Inflate the IDAT stream and hand each unfiltered scanline to onRow(y, rowBytes). */
  function pngRows(hdr, onRow) {
    var bpp = hdr.depth === 16 ? 2 : 1;
    var len = hdr.w * bpp;
    var cur = new Uint8Array(len), prev = new Uint8Array(len), tmp;
    var y = 0, col = -1, ft = 0;
    var reader = new Blob(hdr.idat).stream().pipeThrough(new DecompressionStream('deflate')).getReader();
    function feed(ch) {
      var i = 0, n = ch.length;
      while (i < n && y < hdr.h) {
        if (col < 0) { ft = ch[i++]; col = 0; continue; }
        var take = len - col;
        if (take > n - i) take = n - i;
        cur.set(ch.subarray(i, i + take), col);
        col += take; i += take;
        if (col === len) {
          unfilter(ft, cur, prev, bpp, len);
          onRow(y, cur);
          tmp = prev; prev = cur; cur = tmp;
          y++; col = -1;
        }
      }
    }
    function pump() {
      return reader.read().then(function (r) {
        if (r.done) {
          if (y < hdr.h) throw new Error('PNG stream ended at row ' + y + ' of ' + hdr.h);
          return;
        }
        feed(r.value);
        return pump();
      });
    }
    return pump();
  }

  /* ---------------- load ---------------- */
  function load(src, opts) {
    opts = opts || {};
    if (!supported()) return Promise.reject(new Error(NO_DS_MSG));
    var t = { start: now() }, bytes, gzBytes = 0;
    var p = (typeof src === 'string')
      ? fetch(src).then(function (r) {
          if (!r.ok) throw new Error('MRMS HTTP ' + r.status);
          return r.arrayBuffer();
        })
      : Promise.resolve(src);
    return p.then(function (ab) {
      bytes = ab instanceof Uint8Array ? ab : new Uint8Array(ab);
      gzBytes = bytes.length;
      t.fetched = now();
      return gunzip(bytes);
    }).then(function (grib) {
      t.gunzipped = now();
      var g = parseGrib(grib), gribLen = grib.length;
      var hdr = pngHeader(g.data);
      if (hdr.w !== g.nx || hdr.h !== g.ny) throw new Error('PNG ' + hdr.w + 'x' + hdr.h + ' does not match grid ' + g.nx + 'x' + g.ny);
      var info = PARAMS[g.discipline + '.' + g.category + '.' + g.number] ||
        { name: 'param ' + g.discipline + '.' + g.category + '.' + g.number, units: '?', missing: null, noCoverage: null };
      var factor = info.factor || 1;

      // Geometry in "north row first" orientation.
      var lon1 = g.lo1 > 180 ? g.lo1 - 360 : g.lo1;
      var dlat = g.dj, dlon = g.di;
      var south2north = !!(g.scan & 0x40);
      var latN = south2north ? g.la2 : g.la1;

      // Crop window (inclusive-exclusive) in north-first row/col indices.
      var r0 = 0, r1 = g.ny, c0 = 0, c1 = g.nx;
      if (opts.bbox) {
        var s = opts.bbox[0][0], w = opts.bbox[0][1], nn = opts.bbox[1][0], e = opts.bbox[1][1];
        r0 = Math.max(0, Math.floor((latN - nn) / dlat)); r1 = Math.min(g.ny, Math.ceil((latN - s) / dlat) + 1);
        c0 = Math.max(0, Math.floor((w - lon1) / dlon)); c1 = Math.min(g.nx, Math.ceil((e - lon1) / dlon) + 1);
        if (r1 <= r0 || c1 <= c0) throw new Error('bbox does not intersect the MRMS grid');
      }
      var cw = c1 - c0, chh = r1 - r0;
      var st = opts.stride || Math.max(1, Math.ceil(Math.sqrt(cw * chh / (opts.maxCells || 25e6))));
      var onx = Math.ceil(cw / st), ony = Math.ceil(chh / st);
      var out = new Float32Array(onx * ony);

      // Lookup table raw -> value (exact MRMS formula, then unit factor).
      var nlut = hdr.depth === 16 ? 65536 : 256;
      var lut = new Float32Array(nlut);
      var e2 = Math.pow(2, g.E), d10 = Math.pow(10, g.D);
      for (var k = 0; k < nlut; k++) lut[k] = ((g.R + k * e2) / d10) * factor;
      // Sentinels decode exactly (-3, -1, 0); round the float32 noise off them.
      if (info.noCoverage !== null) for (k = 0; k < nlut; k++) if (Math.abs(lut[k] - info.noCoverage) < 1e-6) lut[k] = info.noCoverage;
      if (info.missing !== null) for (k = 0; k < nlut; k++) if (Math.abs(lut[k] - info.missing) < 1e-6) lut[k] = info.missing;

      var is16 = hdr.depth === 16;
      function onRow(yFile, row) {
        var y = south2north ? (g.ny - 1 - yFile) : yFile;
        if (y < r0 || y >= r1) return;
        var oy = ((y - r0) / st) | 0, base = oy * onx, first = ((y - r0) % st) === 0, c, j, v, o, m, cc, cend;
        if (st === 1) {
          if (is16) { for (c = c0, j = c0 * 2, o = base; c < c1; c++, j += 2, o++) out[o] = lut[(row[j] << 8) | row[j + 1]]; }
          else { for (c = c0, o = base; c < c1; c++, o++) out[o] = lut[row[c]]; }
          return;
        }
        if (st === 2 && !is16) { // RotationTrack 0.005 deg -> 0.01 deg fast path
          var a, bb;
          for (c = c0, o = base; c + 1 < c1; c += 2, o++) {
            a = lut[row[c]]; bb = lut[row[c + 1]]; if (bb > a) a = bb;
            if (first || a > out[o]) out[o] = a;
          }
          if (c < c1) { a = lut[row[c]]; if (first || a > out[o]) out[o] = a; }
          return;
        }
        for (c = c0, o = base; c < c1; c += st, o++) {
          cend = c + st; if (cend > c1) cend = c1;
          m = -Infinity;
          for (cc = c; cc < cend; cc++) {
            v = is16 ? lut[(row[cc * 2] << 8) | row[cc * 2 + 1]] : lut[row[cc]];
            if (v > m) m = v;
          }
          if (first || m > out[o]) out[o] = m;
        }
      }

      t.parsed = now();
      return pngRows(hdr, onRow).then(function () {
        t.done = now();
        return {
          nx: onx, ny: ony,
          lat1: latN - (r0 + (st - 1) / 2) * dlat,
          lon1: lon1 + (c0 + (st - 1) / 2) * dlon,
          dlat: dlat * st, dlon: dlon * st,
          time: g.time, values: out,
          param: info.name, units: info.units, fileUnits: info.fileUnits || info.units,
          missing: { missing: info.missing, noCoverage: info.noCoverage,
            note: info.missing === info.noCoverage ? 'one sentinel: no echo and no coverage are both ' + info.missing
              : info.missing + ' = no hail (inside coverage), ' + info.noCoverage + ' = no radar coverage' },
          stride: st,
          crop: { r0: r0, r1: r1, c0: c0, c1: c1 },
          source: { nx: g.nx, ny: g.ny, lat1: latN, lon1: lon1, dlat: dlat, dlon: dlon, R: g.R, E: g.E, D: g.D,
            bits: hdr.depth, gzBytes: gzBytes, gribBytes: gribLen, pngBytes: g.data.length, scan: g.scan },
          timing: { fetch: t.fetched - t.start, gunzip: t.gunzipped - t.fetched, parse: t.parsed - t.gunzipped,
            png: t.done - t.parsed, decode: t.done - t.fetched, total: t.done - t.start }
        };
      });
    });
  }

  /* ---------------- point queries ---------------- */
  function sample(grid, lat, lon) {
    var r = Math.round((grid.lat1 - lat) / grid.dlat), c = Math.round((lon - grid.lon1) / grid.dlon);
    if (r < 0 || c < 0 || r >= grid.ny || c >= grid.nx) return null;
    return grid.values[r * grid.nx + c];
  }
  function maxNear(grid, lat, lon, miles) {
    var R = 3958.8, rad = Math.PI / 180, coslat = Math.cos(lat * rad);
    var dr = Math.ceil(miles / (R * rad * grid.dlat)), dc = Math.ceil(miles / (R * rad * grid.dlon * Math.max(coslat, 0.01)));
    var rc = Math.round((grid.lat1 - lat) / grid.dlat), cc = Math.round((lon - grid.lon1) / grid.dlon);
    var best = null, bestD = 0;
    for (var r = Math.max(0, rc - dr); r <= Math.min(grid.ny - 1, rc + dr); r++) {
      var la = grid.lat1 - r * grid.dlat, dy = (la - lat) * rad * R;
      for (var c = Math.max(0, cc - dc); c <= Math.min(grid.nx - 1, cc + dc); c++) {
        var v = grid.values[r * grid.nx + c];
        if (!(v > 0)) continue;
        var lo = grid.lon1 + c * grid.dlon, dx = (lo - lon) * rad * R * Math.cos((la + lat) / 2 * rad);
        var d = Math.sqrt(dx * dx + dy * dy);
        if (d > miles) continue;
        if (!best || v > best.value || (v === best.value && d < bestD)) { best = { value: v, lat: la, lon: lo, miles: d }; bestD = d; }
      }
    }
    return best || { value: null, lat: null, lon: null, miles: null };
  }
  function stats(grid) {
    var v = grid.values, n = v.length, max = -Infinity, mi = -1, pos = 0, nc = 0, ms = 0, x;
    var ncv = grid.missing.noCoverage, msv = grid.missing.missing;
    for (var i = 0; i < n; i++) {
      x = v[i];
      if (x > 0) { pos++; if (x > max) { max = x; mi = i; } }
      else if (x === msv) ms++;
      else if (x === ncv) nc++;
    }
    var r = (mi / grid.nx) | 0, c = mi - r * grid.nx;
    return { cells: n, positive: pos, noCoverage: ncv === msv ? null : nc, missing: ms,
      max: mi < 0 ? null : max, maxRow: r, maxCol: c,
      maxLat: mi < 0 ? null : grid.lat1 - r * grid.dlat, maxLon: mi < 0 ? null : grid.lon1 + c * grid.dlon };
  }

  /* ---------------- colour scales ---------------- */
  var MM = 25.4;
  var MESH_BANDS = [ // lower bound in inches, colour, label
    [0.25, [168, 222, 160, 200], '0.25'],
    [0.50, [88, 186, 96, 215], '0.50'],
    [0.75, [30, 130, 55, 225], '0.75 penny'],
    [1.00, [245, 226, 60, 235], '1.00 quarter'],
    [1.25, [247, 186, 40, 240], '1.25 half dollar'],
    [1.50, [240, 136, 30, 245], '1.50 ping pong'],
    [1.75, [228, 76, 32, 250], '1.75 golf ball'],
    [2.00, [200, 26, 30, 250], '2.00 hen egg'],
    [2.50, [150, 8, 22, 252], '2.50 tennis ball'],
    [2.75, [200, 24, 150, 255], '2.75 baseball'],
    [3.00, [232, 72, 210, 255], '3.00 teacup'],
    [4.00, [255, 170, 250, 255], '4.00 softball']
  ];
  var ROT_BANDS = [ // lower bound in s^-1
    [0.004, [255, 236, 170, 170], '0.004'],
    [0.006, [254, 208, 120, 200], '0.006'],
    [0.008, [252, 164, 72, 220], '0.008'],
    [0.010, [240, 112, 44, 235], '0.010'],
    [0.012, [222, 62, 34, 245], '0.012'],
    [0.015, [184, 24, 28, 250], '0.015'],
    [0.020, [128, 8, 16, 255], '0.020'],
    [0.030, [80, 0, 10, 255], '0.030']
  ];
  var CLEAR = [0, 0, 0, 0];
  function band(bands, v) {
    for (var i = bands.length - 1; i >= 0; i--) if (v >= bands[i][0]) return bands[i][1];
    return CLEAR;
  }
  var scales = {
    mesh: function (mm) { return (mm > 0) ? band(MESH_BANDS, mm / MM) : CLEAR; },
    rotation: function (s) { return (s > 0) ? band(ROT_BANDS, s) : CLEAR; }
  };
  function legend(kind) {
    var rot = kind === 'rotation', bands = rot ? ROT_BANDS : MESH_BANDS;
    var h = '<div class="bv-mrms-legend" style="font:11px/1.35 ui-monospace,Menlo,monospace;color:#1d2a33">' +
      '<div style="font-weight:600;letter-spacing:.06em;margin-bottom:3px">' +
      (rot ? 'ROTATION TRACK (s<sup>-1</sup>)' : 'HAIL SIZE (MESH, in)') + '</div>';
    for (var i = 0; i < bands.length; i++) {
      var c = bands[i][1];
      h += '<div style="display:flex;align-items:center;gap:6px"><span style="display:inline-block;width:14px;height:10px;border-radius:2px;background:rgba(' +
        c[0] + ',' + c[1] + ',' + c[2] + ',' + (c[3] / 255).toFixed(2) + ')"></span>' + bands[i][2] + (i === bands.length - 1 ? '+' : '') + '</div>';
    }
    return h + '</div>';
  }

  /* ---------------- canvas overlay ---------------- */
  // bounds [[s,w],[n,e]]; rows are spaced in Web Mercator so L.imageOverlay lines up exactly.
  function mercY(lat) { var r = lat * Math.PI / 180; return Math.log(Math.tan(Math.PI / 4 + r / 2)); }
  function invMercY(y) { return (2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180 / Math.PI; }
  function canvasOverlay(grid, bounds, colorFn, opts) {
    opts = opts || {};
    colorFn = colorFn || (grid.units === 'mm' ? scales.mesh : scales.rotation);
    var s = bounds[0][0], w = bounds[0][1], n = bounds[1][0], e = bounds[1][1];
    var W = Math.max(1, Math.round(opts.width || 1024));
    var yN = mercY(n), yS = mercY(s), xspan = (e - w) * Math.PI / 180;
    var H = Math.max(1, Math.round(W * (yN - yS) / xspan));
    var cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    var ctx = cv.getContext('2d'), img = ctx.createImageData(W, H), px = img.data;
    var v = grid.values, nx = grid.nx, ny = grid.ny;
    // Column spans per output x (grid cell edges at lon1 +/- dlon/2).
    var cs = new Int32Array(W), ce = new Int32Array(W), x, y;
    for (x = 0; x < W; x++) {
      var la = w + (e - w) * x / W, lb = w + (e - w) * (x + 1) / W;
      var a = Math.floor((la - grid.lon1) / grid.dlon + 0.5), b = Math.ceil((lb - grid.lon1) / grid.dlon + 0.5);
      if (b <= a) b = a + 1;
      cs[x] = Math.max(0, a); ce[x] = Math.min(nx, b);
    }
    for (y = 0; y < H; y++) {
      var latT = invMercY(yN - (yN - yS) * y / H), latB = invMercY(yN - (yN - yS) * (y + 1) / H);
      var rs = Math.floor((grid.lat1 - latT) / grid.dlat + 0.5), re = Math.ceil((grid.lat1 - latB) / grid.dlat + 0.5);
      if (re <= rs) re = rs + 1;
      if (rs < 0) rs = 0; if (re > ny) re = ny;
      if (rs >= re) continue;
      for (x = 0; x < W; x++) {
        if (cs[x] >= ce[x]) continue;
        var m = -Infinity;
        for (var r = rs; r < re; r++) {
          var o = r * nx;
          for (var c = cs[x]; c < ce[x]; c++) if (v[o + c] > m) m = v[o + c];
        }
        if (!(m > 0)) continue;
        var col = colorFn(m);
        if (!col[3]) continue;
        var p = (y * W + x) * 4;
        px[p] = col[0]; px[p + 1] = col[1]; px[p + 2] = col[2]; px[p + 3] = col[3];
      }
    }
    ctx.putImageData(img, 0, 0);
    return cv;
  }

  window.bvMRMS = {
    bucket: BUCKET,
    products: {
      mesh60: 'MESH_Max_60min_00.50', mesh1440: 'MESH_Max_1440min_00.50',
      rot60: 'RotationTrack60min_00.50', rot1440: 'RotationTrack1440min_00.50'
    },
    supported: supported,
    unsupportedMessage: NO_DS_MSG,
    latest: latest,
    load: load,
    sample: sample,
    maxNear: maxNear,
    stats: stats,
    canvasOverlay: canvasOverlay,
    scales: scales,
    legend: legend,
    _params: PARAMS
  };
})();
