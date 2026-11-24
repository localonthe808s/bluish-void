/* bvGeese -- skeins of geese in the volumetric sky (2026-11-24, user: "i would love Geese for all locations").
   Canada geese live across North America (and greylags and Canadas across Europe): they fly every day, all year, between the
   water where they roost and the fields where they feed, and in spring and fall they migrate in bigger, higher skeins.
   Here every goose is a point in the SAME 3-D world as the clouds (x north = screen right, y up, z west = away, metres),
   projected through the same camera, so a skein shrinks with distance and each wing foreshortens as it beats.
     - THE DAY: commuting skeins cluster around dawn (first song to an hour after sunrise) and dusk (an hour before sunset
       to last song), a few at midday; none at night. Commuters fly low (70-220 m) and near (250-700 m).
     - MIGRATION (Mar-Apr, Oct-Nov; shoulders Feb, May, Sep, Dec): larger skeins (18-45), higher (350-900 m) and farther,
       heading poleward in spring and toward the equator in fall (the hemisphere from o.lat), at any hour of the day.
     - THE SKEIN: a V, a J (one arm long) or an echelon line; each bird holds its slot behind and beside the one ahead with
       a little wander, the arms ripple, and the wingbeat runs down each arm (each bird a beat later). Geese hardly glide.
     - THE WIND: the skein's track is its airspeed (17 m/s) plus the wind, so it crabs across a crosswind.
   Usage: var g = bvGeese(canvas, { W, H, tH, tilt, lat, seed }); g.set({ on, sun: { el, eve, month, first, last, rise, set },
          wind: [x, z] }); g.now(kind); g.stats(); g.destroy(). first/last/rise/set are minutes of the day; el the sun's
          height (deg). Drawn on its own canvas; nothing outside can restart it. */
(function(){
  function rng(seed){ var s = seed >>> 0 || 1; return function(){ s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
  window.bvGeese = function(cv, o){
    o = Object.assign({ W: 684, H: 270, tH: 0.7, tilt: 0.03, lat: 40.7, seed: 11, on: true, sun: null, wind: [0, 0], E: 2.6 }, o || {});
    var ctx = cv.getContext('2d'), R = rng(o.seed), dpr = Math.min(2, window.devicePixelRatio || 1), W, H, tV, e0, ce, se, F;
    var SK = [], t = 0, last = 0, raf = 0, alive = true, next = 4, st = { skeins: 0, birds: 0, made: 0 };
    function dims(w, h){ W = w; H = h; cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = W + 'px'; cv.style.height = H + 'px';
      tV = o.tH / (W / H); e0 = o.tilt + Math.atan(tV); ce = Math.cos(e0); se = Math.sin(e0); F = (W / 2) / o.tH; }
    dims(o.W, o.H);
    /* world (m) -> screen px; null behind the camera. The inverse of the shader's rd = (dc.x, dc.y ce + dc.z se, -dc.y se + dc.z ce) */
    function P(x, y, z){ var cy = y * ce - z * se, cz = y * se + z * ce; if (cz < 1) return null; return [W * (0.5 + x / cz / (2 * o.tH)), H * (0.5 - cy / cz / (2 * tV)), cz]; }
    function month(){ return (o.sun && o.sun.month) || 6; }
    function migFactor(){ var m = month(), south = o.lat < 0, mm = south ? ((m + 5) % 12) + 1 : m; return [0.4, 1.4, 2.6, 2.6, 1.4, 0.3, 0.3, 0.4, 1.4, 2.6, 2.6, 1.4][mm - 1]; }   /* southern hemisphere: the seasons shift six months */
    function migDir(){ var m = month(), south = o.lat < 0, mm = south ? ((m + 5) % 12) + 1 : m; var spring = mm >= 2 && mm <= 6; return (spring ? 1 : -1) * (south ? -1 : 1); }   /* +1 = north (screen right) */
    function rates(){   /* skeins per minute: [commute, migration] */
      var s = o.sun; if (!s || !o.on) return [0, 0]; var m = s.min != null ? s.min : 720, c = 0.12;
      if (s.first != null && s.rise != null && m >= s.first && m <= s.rise + 60) c = 1.1;
      if (s.set != null && s.last != null && m >= s.set - 60 && m <= s.last) c = 1.1;
      var mf = migFactor(); return [c, mf > 1 ? 0.35 * (mf - 1) : 0]; }
    function makeSkein(kind){
      var mig = kind === 'mig', n = mig ? 18 + Math.floor(R() * 28) : 9 + Math.floor(R() * 16);
      /* FAR Vs ONLY (user 11-24: "dont show ones close up either, they arent detailed enough, i prefer far Vs"): every skein high and well out */
      var alt = mig ? 450 + R() * 450 : 300 + R() * 300, dist = mig ? 1800 + R() * 1700 : 1200 + R() * 1000;
      /* DIRECTION BY SEASON (user 11-24: "geese should only be going south (left) this time of year"): in the migration seasons every
         skein heads the way the season goes (fall south, spring north); only in summer and midwinter do commuters go either way */
      var dir = migFactor() > 1 ? migDir() : (R() < 0.5 ? 1 : -1), ang = (R() - 0.5) * 0.6;
      var hx = dir * Math.cos(ang), hz = Math.sin(ang), span = dist * o.tH * 1.25;   /* start well outside the side of the view */
      var shape = R(), arms = shape < 0.85 ? 'V' : 'J', half = (28 + R() * 14) * Math.PI / 180;
      var lx = -dir * span, lz = dist - hz / Math.max(Math.abs(hx), 0.3) * span * 0.6 * dir;   /* so it passes near the chosen distance mid-view */
      var B = [], left = 0, right = 0;
      for (var i = 0; i < n; i++){ var side = i === 0 ? 0 : arms === 'line' ? 1 : arms === 'J' ? (R() < 0.72 ? 1 : -1) : (i % 2 ? 1 : -1), rank = side > 0 ? ++right : side < 0 ? ++left : 0;
        B.push({ side: side, rank: rank, sp: 3.6 + R() * 1.4, wob: R() * 6.28, wf: 0.15 + R() * 0.2, ph: R() * 0.6, hz: 2.6 + R() * 0.5, up: (R() - 0.5) * 1.5 }); }
      st.made++; return { mig: mig, B: B, x: lx, y: alt, z: Math.max(150, lz), hx: hx, hz: hz, half: half, as: 15.5 + R() * 3, t0: t, life: 0, dir: dir, sway: R() * 6.28 }; }
    function birdPos(s, b){   /* its slot: back along the heading by rank x spacing, out to its side by tan(half angle) */
      var back = b.rank * b.sp, lat = b.side * b.rank * b.sp * Math.tan(s.half), wav = Math.sin(t * 0.45 + b.rank * 0.35 + s.sway) * 0.012 * b.rank * b.sp;   /* the arms ripple */
      var px = -s.hz, pz = s.hx;   /* the skein's left-right axis */
      var wx = Math.sin(t * b.wf + b.wob) * 0.7, wy = Math.sin(t * b.wf * 1.3 + b.wob * 2) * 0.5 + b.up;
      return [s.x - s.hx * back + px * (lat + wav + wx), s.y + wy - b.rank * 0.15, s.z - s.hz * back + pz * (lat + wav + wx)]; }
    function step(dt){ t += dt;
      var r = rates(); next -= dt; if (next <= 0){ var tot = r[0] + r[1]; if (tot > 0 && SK.length < 3){ SK.push(makeSkein(R() * tot < r[1] ? 'mig' : 'com')); } next = tot > 0 ? (40 + R() * 50) / Math.max(tot, 0.05) * 0.9 : 6; }
      var wx = (o.wind && o.wind[0]) || 0, wz = (o.wind && o.wind[1]) || 0;
      for (var i = SK.length - 1; i >= 0; i--){ var s = SK[i]; s.x += (s.hx * s.as + wx) * dt; s.z += (s.hz * s.as + wz) * dt; s.y += Math.sin(t * 0.21 + s.sway) * 0.4 * dt; s.life += dt;
        var c = P(s.x, s.y, s.z), out = c && ((s.dir > 0 && c[0] > W + 0.25 * W) || (s.dir < 0 && c[0] < -0.25 * W)) && s.life > 8;
        if (out || s.life > 400 || s.z < 80) SK.splice(i, 1); }
      st.skeins = SK.length; }
    function draw(){ ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H); var nb = 0;
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      SK.forEach(function(s){ var ux = -s.hz, uz = s.hx;   /* wing axis */
        s.B.forEach(function(b){ var p = birdPos(s, b), c = P(p[0], p[1], p[2]); if (!c || c[0] < -40 || c[0] > W + 40 || c[1] < -40 || c[1] > H + 10) return; nb++;
          var E = o.E, hx = s.hx, hz = s.hz, ph = t * b.hz * 6.2832 - b.rank * 0.9 + b.ph, el = 0.6 * Math.sin(ph + 0.38 * Math.sin(ph)), ca = Math.cos(el), sa = Math.sin(el);   /* the beat: a raised wing foreshortens seen from below */
          /* a point on the goose in body metres: f forward, r to its right (+ = the skein's left-right axis), u up */
          function B(f, r, u){ var rr = r * ca, uu = u + Math.abs(r) * sa; return P(p[0] + (hx * f + ux * rr) * E, p[1] + uu * E, p[2] + (hz * f + uz * rr) * E); }
          /* SILHOUETTE FROM BELOW (Canada goose: span 1.6 m, body + neck ~1 m): broad inner wings tapering to pointed hands swept a
             little back, a heavy body, a long thin neck and a small dark head (user 11-24 screenshot: the first try read as T and I marks) */
          var wing = [[0.13, 0.12], [0.1, 0.42], [0.02, 0.62], [-0.12, 0.82], [-0.14, 0.76], [-0.1, 0.5], [-0.14, 0.14]];
          var sk = ctx; sk.globalAlpha = 0.93 * Math.max(0.35, 1 - c[2] / 5000); sk.fillStyle = '#2b2622';
          [1, -1].forEach(function(sd){ sk.beginPath(); var ok = true; wing.forEach(function(w, k){ var q = B(w[0], sd * w[1], 0); if (!q){ ok = false; return; } if (k) sk.lineTo(q[0], q[1]); else sk.moveTo(q[0], q[1]); }); if (ok){ sk.closePath(); sk.fill(); } });
          var body = [[0.3, 0.07], [0.12, 0.13], [-0.15, 0.12], [-0.42, 0.05], [-0.48, 0], [-0.42, -0.05], [-0.15, -0.12], [0.12, -0.13], [0.3, -0.07]];
          sk.beginPath(); var okb = true; body.forEach(function(w, k){ var q = B(w[0], w[1], 0); if (!q){ okb = false; return; } if (k) sk.lineTo(q[0], q[1]); else sk.moveTo(q[0], q[1]); }); if (okb){ sk.closePath(); sk.fill(); }
          var n0 = B(0.28, 0, 0), n1 = B(0.72, 0, 0.02), hd = B(0.8, 0, 0.03); if (n0 && n1 && hd){ var kpx = F / c[2] * E;   /* px per metre here */
            sk.strokeStyle = '#1d1915'; sk.lineCap = 'round'; sk.lineWidth = Math.max(0.6, 0.075 * kpx); sk.beginPath(); sk.moveTo(n0[0], n0[1]); sk.lineTo(n1[0], n1[1]); sk.stroke();
            sk.fillStyle = '#141110'; sk.beginPath(); sk.arc(hd[0], hd[1], Math.max(0.5, 0.06 * kpx), 0, 6.2832); sk.fill(); } }); });
      ctx.globalAlpha = 1; st.birds = nb; }
    function frame(now){ raf = 0; if (!alive) return; var dt = last ? Math.min(0.1, (now - last) / 1000) : 1 / 30; last = now; step(dt); draw(); raf = requestAnimationFrame(frame); }
    raf = requestAnimationFrame(frame);
    return {
      set: function(p){ if (p.W || p.H) dims(p.W || W, p.H || H); ['on', 'sun', 'wind', 'lat', 'tH', 'tilt'].forEach(function(k){ if (p[k] !== undefined) o[k] = p[k]; }); if (p.tH || p.tilt) dims(W, H); if (!o.on) SK.length = 0; },
      now: function(kind){ SK.push(makeSkein(kind || 'com')); },
      stats: function(){ var r = rates(); return { skeins: SK.length, birds: st.birds, made: st.made, perMin: r, mig: migFactor(), dir: migDir() }; },
      destroy: function(){ alive = false; if (raf) cancelAnimationFrame(raf); }
    };
  };
})();
