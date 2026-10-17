/* bvSwellField -- THE BASIN's SURF swell solver, lifted out of the map lab so any coast can use it (2026-10-17, user: "make
   sure the waves youre making are at the same high value weve already built for LA and NYC"). The math is the lab's own
   (_maplab/index.html: swellExposure, swellTravelTime, swellNoise and the per-pixel field build in paint()), copied line for
   line and kept in step with it by hand -- the lab itself still runs its own copy, untouched. What differs is only where the
   inputs come from: the lab reads its baked LA depth grid and LA island mask; here the caller hands over a depth grid and
   (optionally) a coarse land mask for whatever piece of coast is in view, both read from NOAA's DEM mosaic.
     window.bvSwellTravel(D, dirFrom, T, Hs)   the eikonal + energy-flux solve over D (cached on D.solved)
     window.bvSwellNoise()                     the 256 x 256 noise tile the sets and crests are read from
     window.bvSwellField(o)                    the per-pixel field bvSeaGL draws (sea_gl.js)
   o: { D: { w, h, depth (Float32Array, m, positive down; <= 0 is land), W, S, E, N, step (deg, same in lon and lat) },
        ctx: optional { w, h, land (Uint8Array), W, N, cell } -- land beyond D for the islands' and capes' shadows
             (beyond both = open ocean),
        RW, RH, lonAt(x), latAt(y) -- the field's pixels (x, y in field px; the centre of pixel i is i + .5),
        water: Uint8Array(RW * RH), 1 = sea,
        mpp: ground metres per field pixel,
        lead: { dir (FROM, deg), tp (s), hs (m) }, second: optional { dir, tp, hs } }
   returns { RW, RH, N, IDX, PH, UU, LI, AM, BR, SP, SH, PH2, A2, NZ, consts: { amp, w2, r2, TV, lead, mpp } } or null. */
(function(){
  /* exposure of one point of sea to a swell from `dir` (degrees it comes FROM): 0..1 -- the lab's swellExposure, marching
     over the solve grid's own land first, then the coarse mask, and calling anything beyond both open ocean */
  function exposure(D, C, lon, lat, dir, skipKm){
    var FAN = [[-20, .1], [-10, .2], [0, .4], [10, .2], [20, .1]], kmLat = 111.32, kmLon = 111.32 * Math.cos(lat * Math.PI / 180), ex = 0;
    for (var f = 0; f < FAN.length; f++){
      var a = (dir + FAN[f][0]) * Math.PI / 180, dLon = Math.sin(a) / kmLon, dLat = Math.cos(a) / kmLat, open = 1;
      for (var k = (skipKm || 0); k < 320; k++){
        var lo = lon + dLon * k, la = lat + dLat * k;
        var x = Math.floor((lo - D.W) / D.step), y = Math.floor((D.N - la) / D.step);
        if (x >= 0 && y >= 0 && x < D.w && y < D.h){ if (!(D.depth[y * D.w + x] > 0)){ open = 0; break; } continue; }
        if (!C) break;
        x = Math.floor((lo - C.W) / C.cell); y = Math.floor((C.N - la) / C.cell);
        if (x < 0 || y < 0 || x >= C.w || y >= C.h) break;          // off the mask: open ocean
        if (C.land[y * C.w + x]){ open = 0; break; }
      }
      ex += open * FAN[f][1];
    }
    return ex;
  }
  /* HOW THE SWELL BENDS -- the lab's swellTravelTime, unchanged: Eckart's dispersion, fast-sweeping eikonal from a plane wave
     on the upstream edges, then energy flux walked in travel-time order (shoaling, focusing, breaking at 0.78 of the depth),
     three smoothing passes standing in for diffraction. */
  function travel(D, dirFrom, T, Hs, C){
    Hs = Hs > 0 ? Hs : 0.6;
    D.solved = D.solved || {};
    var key = Math.round(dirFrom / 3) * 3 + '|' + Math.round(T) + '|' + (Math.round(Hs * 5) / 5) + (C ? '|c' : '');
    if (D.solved[key]) return D.solved[key];
    var w = D.w, h = D.h, n = w * h, tau = new Float32Array(n), slow = new Float32Array(n), fixed = new Uint8Array(n);
    var g = 9.81, om = 2 * Math.PI / T, c0 = g * T / (2 * Math.PI), lat0 = (D.S + D.N) / 2;
    var hx = D.step * 111320 * Math.cos(lat0 * Math.PI / 180), hy = D.step * 111320;
    for (var i = 0; i < n; i++){
      var dep = D.depth[i];
      if (dep <= 0){ slow[i] = 0; tau[i] = Infinity; continue; }            // land
      slow[i] = 1 / (c0 * Math.sqrt(Math.tanh(om * om * Math.max(dep, 2) / g)));
      tau[i] = 1e12;
    }
    var th = (dirFrom + 180) * Math.PI / 180, te = Math.sin(th), tn = Math.cos(th);
    /* THE SWELL ENTERS ONLY FROM THE OPEN SEA (2026-10-17, national map). The lab's grid edges are all open Pacific; on an
       arbitrary coast an upstream edge can cut through a lagoon or a sound (Pamlico, behind the Outer Banks), and a plane
       wave seeded there floods water the ocean swell never reaches. With a land mask C, an edge cell is seeded only when the
       swell's own fan, looking upwind from it, reaches open water -- the same exposure test that lights the crests. If that
       leaves no seed at all, every edge is seeded as before. */
    var okSeed = null;
    if (C){
      /* AND ONLY FROM WATER DEEPER THAN 10 M (2026-10-17): the coarse mask's ~1 km cells miss a barrier island a few hundred
         metres wide, so from inside Pamlico Sound the fan "saw" open sea straight through Hatteras Island and the sound was
         seeded as ocean. The sound is 2-7 m deep; the open sea at any upstream edge of a view is far deeper. */
      okSeed = function(x, y){ return D.depth[y * w + x] >= 10 && exposure(D, C, D.W + (x + 0.5) * D.step, D.N - (y + 0.5) * D.step, dirFrom, 0) >= 0.3; };
    }
    var seeded = 0;
    var seed = function(x, y){
      var k = y * w + x; if (!slow[k]) return;
      if (okSeed && !okSeed(x, y)) return;
      tau[k] = ((x * hx) * te + ((h - 1 - y) * hy) * tn) / c0; fixed[k] = 1; seeded++;
    };
    var seedAll = function(){
      for (var x = 0; x < w; x++){ if (tn > 0) seed(x, h - 1); if (tn < 0) seed(x, 0); }
      for (var y = 0; y < h; y++){ if (te > 0) seed(0, y); if (te < 0) seed(w - 1, y); }
    };
    seedAll();
    if (okSeed && !seeded){ okSeed = null; seedAll(); }
    var x, y;
    var ax = 1 / (hx * hx), ay = 1 / (hy * hy);
    var upd = function(x, y){
      var k = y * w + x; if (!slow[k] || fixed[k]) return;
      var a = Math.min(x > 0 ? tau[k - 1] : Infinity, x < w - 1 ? tau[k + 1] : Infinity);
      var b = Math.min(y > 0 ? tau[k - w] : Infinity, y < h - 1 ? tau[k + w] : Infinity);
      if (a > 1e11 && b > 1e11) return;
      var s = slow[k], t;
      var one = Math.min(a + s * hx, b + s * hy);
      if (a > 1e11 || b > 1e11) t = one;
      else {
        var A = ax + ay, B = -2 * (a * ax + b * ay), C = a * a * ax + b * b * ay - s * s, disc = B * B - 4 * A * C;
        t = disc >= 0 ? (-B + Math.sqrt(disc)) / (2 * A) : one;
        if (t < Math.max(a, b)) t = one;
      }
      if (t < tau[k]) tau[k] = t;
    };
    for (var it = 0; it < 3; it++){
      for (y = 0; y < h; y++) for (x = 0; x < w; x++) upd(x, y);
      for (y = 0; y < h; y++) for (x = w - 1; x >= 0; x--) upd(x, y);
      for (y = h - 1; y >= 0; y--) for (x = 0; x < w; x++) upd(x, y);
      for (y = h - 1; y >= 0; y--) for (x = w - 1; x >= 0; x--) upd(x, y);
    }
    var order = [], i2;
    for (i2 = 0; i2 < n; i2++) if (slow[i2] && tau[i2] < 1e11) order.push(i2);
    order.sort(function(a, b){ return tau[a] - tau[b]; });
    var cg = new Float32Array(n), F = new Float32Array(n), amp = new Float32Array(n), brk = new Float32Array(n);
    for (i2 = 0; i2 < order.length; i2++){
      var kc = order[i2], cc = 1 / slow[kc], kh = (om / cc) * Math.max(D.depth[kc], 2), sh2 = Math.sinh(2 * kh);
      cg[kc] = 0.5 * cc * (1 + (kh < 18 && sh2 > 1e-6 ? 2 * kh / sh2 : 0));
    }
    var cg0 = c0 / 2;
    for (i2 = 0; i2 < n; i2++) if (fixed[i2]) F[i2] = cg0;
    var tv = function(kk, home){ return (kk >= 0 && kk < n && slow[kk] && tau[kk] < 1e11) ? tau[kk] : tau[home]; };
    for (i2 = 0; i2 < order.length; i2++){
      var k3 = order[i2], f3 = F[k3];
      if (!(f3 > 0)) continue;
      var E = f3 / Math.max(cg[k3], 0.05), A = Math.sqrt(E), dep3 = D.depth[k3], Hlim = 0.78 * dep3;
      if (A * Hs > Hlim){
        brk[k3] = Math.min(1, (A * Hs - Hlim) / Math.max(Hlim, 0.25) + 0.3);
        A = Hlim / Hs; F[k3] = f3 = A * A * cg[k3];
      }
      amp[k3] = A;
      var x3 = k3 % w, y3 = (k3 - x3) / w;
      var gx = (tv(x3 < w - 1 ? k3 + 1 : -1, k3) - tv(x3 > 0 ? k3 - 1 : -1, k3)) / (2 * hx);
      var gy = (tv(y3 < h - 1 ? k3 + w : -1, k3) - tv(y3 > 0 ? k3 - w : -1, k3)) / (2 * hy);
      var gm = Math.sqrt(gx * gx + gy * gy);
      if (!(gm > 1e-12)) continue;
      var wx = Math.abs(gx / gm), wy = Math.abs(gy / gm), sm = wx + wy;
      if (!(sm > 0)) continue;
      var kx = gx > 0 ? (x3 < w - 1 ? k3 + 1 : -1) : (x3 > 0 ? k3 - 1 : -1);
      var ky = gy > 0 ? (y3 < h - 1 ? k3 + w : -1) : (y3 > 0 ? k3 - w : -1);
      var okx = kx >= 0 && slow[kx] && tau[kx] > tau[k3], oky = ky >= 0 && slow[ky] && tau[ky] > tau[k3];
      if (okx && oky){ F[kx] += f3 * wx / sm; F[ky] += f3 * wy / sm; }
      else if (okx) F[kx] += f3;
      else if (oky) F[ky] += f3;
    }
    var tmp = new Float32Array(n);
    for (var pass = 0; pass < 3; pass++){
      for (var yy = 0; yy < h; yy++) for (var xx = 0; xx < w; xx++){
        var kk2 = yy * w + xx;
        if (!slow[kk2]){ tmp[kk2] = 0; continue; }
        var a1 = xx > 0 && slow[kk2 - 1] ? amp[kk2 - 1] : amp[kk2], a2 = xx < w - 1 && slow[kk2 + 1] ? amp[kk2 + 1] : amp[kk2];
        tmp[kk2] = (a1 + 2 * amp[kk2] + a2) / 4;
      }
      for (yy = 0; yy < h; yy++) for (xx = 0; xx < w; xx++){
        var kk3 = yy * w + xx;
        if (!slow[kk3]){ amp[kk3] = 0; continue; }
        var b1 = yy > 0 && slow[kk3 - w] ? tmp[kk3 - w] : tmp[kk3], b2 = yy < h - 1 && slow[kk3 + w] ? tmp[kk3 + w] : tmp[kk3];
        amp[kk3] = Math.min(3, (b1 + 2 * tmp[kk3] + b2) / 4);
      }
    }
    var keys = Object.keys(D.solved); if (keys.length > 5) delete D.solved[keys[0]];
    return (D.solved[key] = { tau: tau, amp: amp, brk: brk, c0: c0, te: te, tn: tn, hx: hx, hy: hy });
  }
  /* the lab's swellNoise: one seeded 256 x 256 tile, two octaves, wrapping, pushed apart */
  var NOISE = null;
  function noise(){
    if (NOISE) return NOISE;
    var S = 256, out = new Float32Array(S * S), seed = 1234567;
    var rnd = function(){ seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
    [[16, 1], [32, 0.45]].forEach(function(oc){
      var n = oc[0], g = new Float32Array(n * n), c = S / n;
      for (var i = 0; i < g.length; i++) g[i] = rnd();
      for (var y = 0; y < S; y++) for (var x = 0; x < S; x++){
        var gx = x / c, gy = y / c, x0 = Math.floor(gx), y0 = Math.floor(gy), fx = gx - x0, fy = gy - y0;
        fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy);
        var x1 = (x0 + 1) % n, y1 = (y0 + 1) % n;
        out[y * S + x] += oc[1] * ((g[y0 * n + x0] * (1 - fx) + g[y0 * n + x1] * fx) * (1 - fy)
                                 + (g[y1 * n + x0] * (1 - fx) + g[y1 * n + x1] * fx) * fy);
      }
    });
    var lo = 1e9, hi = -1e9; for (var k = 0; k < out.length; k++){ if (out[k] < lo) lo = out[k]; if (out[k] > hi) hi = out[k]; }
    for (k = 0; k < out.length; k++){ var v = (out[k] - lo) / (hi - lo); out[k] = v * v * (3 - 2 * v); }
    return (NOISE = out);
  }
  /* the lab blurs its water mask with canvas blur(5px) to read nearness to the sand; three box passes (radii 4, 5, 5, sigma
     ~5.2 px) give the same thing without needing ctx.filter (missing on older Safari) */
  function blurMask(m, RW, RH){
    var o = new Float32Array(m.length), t = new Float32Array(m.length), x, y, k;
    for (k = 0; k < m.length; k++) o[k] = m[k];
    [4, 5, 5].forEach(function(r){
      for (y = 0; y < RH; y++){ var s = 0, row = y * RW; for (x = -r; x <= r; x++) s += o[row + Math.min(RW - 1, Math.max(0, x))];
        for (x = 0; x < RW; x++){ t[row + x] = s / (2 * r + 1); s += o[row + Math.min(RW - 1, x + r + 1)] - o[row + Math.max(0, x - r)]; } }
      for (x = 0; x < RW; x++){ var s2 = 0; for (y = -r; y <= r; y++) s2 += t[Math.min(RH - 1, Math.max(0, y)) * RW + x];
        for (y = 0; y < RH; y++){ o[y * RW + x] = s2 / (2 * r + 1); s2 += t[Math.min(RH - 1, y + r + 1) * RW + x] - t[Math.max(0, y - r) * RW + x]; } }
    });
    return o;
  }
  window.bvSwellTravel = travel;
  window.bvSwellExposure = exposure;
  window.bvSwellNoise = noise;
  window.bvSwellField = function(o){
    var D = o.D, lead = o.lead, second = o.second || null, RW = o.RW, RH = o.RH, water = o.water;
    if (!D || !lead || lead.dir == null || !water) return null;
    /* from here on, the lab's paint() field build */
    var T = Math.max(5, Math.min(22, lead.tp || 10));
    var sol = travel(D, lead.dir, T, lead.hs, o.ctx || { w: 0, h: 0, W: 0, N: 0, cell: 1, land: [] });
    if (second) second = { dir: second.dir, tp: Math.max(5, Math.min(22, second.tp)), hs: second.hs };
    var sol2 = second ? travel(D, second.dir, second.tp, second.hs, o.ctx || { w: 0, h: 0, W: 0, N: 0, cell: 1, land: [] }) : null;
    var gm = o.mpp, L0 = 9.81 * T * T / (2 * Math.PI);
    var Lshown = Math.max(L0, 7 * gm), c0 = 9.81 * T / (2 * Math.PI), K = 2 * Math.PI / Lshown;
    var th = (lead.dir + 180) * Math.PI / 180, te = Math.sin(th), tn = Math.cos(th);
    var nd = blurMask(water, RW, RH);
    var idx = [], PH = [], LI = [], SH = [], UU = [], AM = [], BR = [], SP = [], PH2 = [], A2 = [];
    var om1 = 2 * Math.PI / T;
    if (second){
      var L02 = 9.81 * second.tp * second.tp / (2 * Math.PI), Lshown2 = Math.max(Lshown * L02 / L0, 5 * gm);
      var K2 = 2 * Math.PI / Lshown2, c02 = 9.81 * second.tp / (2 * Math.PI);
      var th2 = (second.dir + 180) * Math.PI / 180, te2 = Math.sin(th2), tn2 = Math.cos(th2);
    }
    var lonOf = new Float64Array(RW), latOf = new Float64Array(RH);
    for (var x = 0; x < RW; x++) lonOf[x] = o.lonAt(x + 0.5);
    for (var y = 0; y < RH; y++) latOf[y] = o.latAt(y + 0.5);
    /* the lab's metres frame (its origin is fixed at -119.3, 33.3 with cos = 0.83); here the solve grid's corner and its own cos */
    var cosM = Math.cos((D.S + D.N) / 2 * Math.PI / 180);
    var CELL = 8, gw = Math.ceil(RW / CELL) + 1, gh = Math.ceil(RH / CELL) + 1, EX = new Float32Array(gw * gh);
    for (var gy = 0; gy < gh; gy++) for (var gx = 0; gx < gw; gx++)
      EX[gy * gw + gx] = exposure(D, o.ctx, o.lonAt(gx * CELL), o.latAt(gy * CELL), lead.dir, 0);
    for (y = 0; y < RH; y++){
      var la = latOf[y], fy = (D.N - la) / D.step - 0.5, ym = (la - D.S) * 111320;
      for (x = 0; x < RW; x++){
        var p = y * RW + x;
        if (!water[p]) continue;
        var lo = lonOf[x], fx = (lo - D.W) / D.step - 0.5, dist, am = 1, br = 0, dep = 4000, amx = 1, d2 = 0, a2 = 0;
        var xm = (lo - D.W) * 111320 * cosM;
        if (sol && fx >= 0 && fy >= 0 && fx < D.w - 1 && fy < D.h - 1){
          var i0 = Math.floor(fx), j0 = Math.floor(fy), ax2 = fx - i0, ay2 = fy - j0, q = j0 * D.w + i0;
          var t00 = sol.tau[q], t10 = sol.tau[q + 1], t01 = sol.tau[q + D.w], t11 = sol.tau[q + D.w + 1], m = Math.min(t00, t10, t01, t11);
          if (m > 1e11) continue;
          if (!(t00 < 1e11)) t00 = m; if (!(t10 < 1e11)) t10 = m; if (!(t01 < 1e11)) t01 = m; if (!(t11 < 1e11)) t11 = m;
          dist = (t00 * (1 - ax2) * (1 - ay2) + t10 * ax2 * (1 - ay2) + t01 * (1 - ax2) * ay2 + t11 * ax2 * ay2) * c0;
          var bl = function(arr){
            return arr[q] * (1 - ax2) * (1 - ay2) + arr[q + 1] * ax2 * (1 - ay2)
                 + arr[q + D.w] * (1 - ax2) * ay2 + arr[q + D.w + 1] * ax2 * ay2;
          };
          am = bl(sol.amp); br = bl(sol.brk); dep = bl(D.depth);
          amx = Math.max(sol.amp[q], sol.amp[q + 1], sol.amp[q + D.w], sol.amp[q + D.w + 1]);
          if (sol2){
            var u00 = sol2.tau[q], u10 = sol2.tau[q + 1], u01 = sol2.tau[q + D.w], u11 = sol2.tau[q + D.w + 1], m2 = Math.min(u00, u10, u01, u11);
            if (m2 < 1e11){
              if (!(u00 < 1e11)) u00 = m2; if (!(u10 < 1e11)) u10 = m2; if (!(u01 < 1e11)) u01 = m2; if (!(u11 < 1e11)) u11 = m2;
              d2 = (u00 * (1 - ax2) * (1 - ay2) + u10 * ax2 * (1 - ay2) + u01 * (1 - ax2) * ay2 + u11 * ax2 * ay2) * c02;
              a2 = bl(sol2.amp);
            }
          }
        } else {
          dist = xm * te + ym * tn;
          if (second){ d2 = xm * te2 + ym * tn2; a2 = 1; }
        }
        var kr = 1 / Math.sqrt(Math.tanh(om1 * om1 * Math.max(dep, 2) / 9.81));
        var fe = (0.5 * L0 - dep) / (0.35 * L0); fe = fe < 0 ? 0 : fe > 1 ? 1 : fe; fe = fe * fe * (3 - 2 * fe);
        var vis = (0.17 + 0.83 * fe) * Math.min(1.9, Math.pow(kr, 0.8));
        var ex = EX[Math.floor(y / CELL) * gw + Math.floor(x / CELL)];
        var uu = (xm * tn - ym * te) / Lshown;
        /* WATER THE SWELL NEVER REACHES (national map, 2026-10-17): the lab's light is exposure times how hard the bottom has
           hold of the wave, and over a shallow lagoon the second term alone lit Pamlico Sound up as one great surf zone. The
           energy solve already knows better -- behind a barrier island no flux arrives except through the inlets -- so the
           light fades out where the solved height falls under ~0.2 of the open sea's. Open water (height ~1) is untouched. */
        var reach = sol ? Math.min(1, am / 0.2) : 1;
        idx.push(p); PH.push(dist * K + 0.5 * Math.sin(uu * 0.33)); LI.push((0.16 + 0.84 * ex) * vis * reach); AM.push(am); BR.push(br);
        SP.push(Math.min(1, Math.max(0, (kr - 1.05) / 1.1)));
        PH2.push(second ? d2 * K2 + 0.6 * Math.sin(uu * 0.21 + 1.3) : 0); A2.push(a2);
        var nv = nd[p], edge = (0.93 - nv) / 0.45; edge = edge < 0 ? 0 : edge > 1 ? 1 : edge;
        SH.push(edge * Math.min(1.4, (0.16 + 0.84 * ex) * Math.min(amx, 2.2)));
        UU.push(uu);
      }
    }
    var N = idx.length; if (!N) return null;
    var amp = Math.max(0.45, Math.min(1, 0.35 + (lead.hs || 0.6) * 3.281 / 7));
    var w2 = second ? Math.min(0.55, second.hs / Math.max(lead.hs || 0.6, 0.2)) : 0, r2 = second ? T / second.tp : 0;
    var ext = 0; for (var e = 0; e < EX.length; e++) ext += EX[e];
    return { RW: RW, RH: RH, N: N, IDX: new Uint32Array(idx), PH: PH, UU: UU, LI: new Float32Array(LI), AM: new Float32Array(AM), BR: new Float32Array(BR),
      SP: new Float32Array(SP), SH: new Float32Array(SH), PH2: PH2, A2: new Float32Array(A2), NZ: noise(), exposure: ext / EX.length,
      consts: { amp: amp, w2: w2, r2: r2, TV: 2.8, lead: { dir: lead.dir, tp: lead.tp, hs: lead.hs }, mpp: gm } };
  };
})();
