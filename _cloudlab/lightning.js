/* bvSkyLightning -- lightning in the volumetric storms (2026-11-24, user: "how can we improve lightning strikes and lightning flashes in the
   clouds"; then "do 1 2 3 4; do 5 but dont soley rely on live strikes, have mandatory strikes and internal glows").
   1  TIMING: a flash is a SEQUENCE. Cloud-to-ground: 2-5 return strokes 40-90 ms apart (the flicker the eye catches), each a sharp peak
      decaying in ~30 ms; branches lit by the first stroke only (later strokes follow the main channel); sometimes a continuing current
      glows on for ~150 ms. In-cloud: 4-10 pulses over 0.25-0.9 s.
   2  TYPES: in-cloud flashes inside the towers (~55 %), cloud-to-ground strikes under the mature cells (~30 %), anvil crawlers running
      downwind under the anvil (~15 %, the fronts only).
   3  THE BOLT IN 3-D: a branching channel built in the cloud world (km: x north = screen right, y up, z west = away) by midpoint
      displacement, from the base to the ground, projected through the clouds' camera: right size for its distance; drawn as core +
      glow, dimmer and softer through rain and distance.
   4  LIGHT FROM THE CHANNEL: u() hands the cloud shader a LINE light (segment A-B, radius R, intensity I) -- the channel or the crawl
      path -- plus G, a faint brightening of the whole sky (stronger at night), and rain, for the precipitation layer.
   5  LIVE: live(x, z) adds a real strike (from the dashboard's Blitzortung client) as a cloud-to-ground strike at its true direction;
      the scheduled flashes ALWAYS run as well, so the storm never goes quiet.
   Usage: var L = bvSkyLightning(canvas); L.scene({ cb, cells: [{x, z, R, mature}], base, near, cal, night, W, H, tH, tilt });
          per frame: L.frame(nowMs) (steps and draws); L.u() -> { A, B, I, R, G, rain, fast }; L.live(x, z); L.stats(). */
(function(){
  function rng(seed){ var s = seed >>> 0 || 1; return function(){ s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
  window.bvSkyLightning = function(cv, o){
    o = Object.assign({ seed: 7 }, o || {});
    var ctx = cv.getContext('2d'), R = rng(o.seed), dpr = Math.min(2, window.devicePixelRatio || 1), SC = null, W = 684, H = 270, tH = 0.7, tV, e0, ce, se;
    var EV = [], next = 0, t = 0, st = { made: 0, live: 0, cg: 0, ic: 0, cr: 0 }, LQ = [], u = { A: [0, 0, 0], B: [0, 0, 0], I: 0, R: 2, G: 0, rain: 0, fast: false }, fastUntil = 0;
    function cam(){ tV = tH / (W / H); e0 = ((SC && SC.tilt) || 0.03) + Math.atan(tV); ce = Math.cos(e0); se = Math.sin(e0); }
    function P(x, y, z){ var cy = y * ce - z * se, cz = y * se + z * ce; if (cz < 0.05) return null; return [W * (0.5 + x / cz / (2 * tH)), H * (0.5 - cy / cz / (2 * tV)), cz]; }
    /* ---- the channel: midpoint displacement in 3-D; wander mostly sideways, a little up and down, shrinking each level ---- */
    function channel(a, b, lv, rough){ var pts = [a, b];
      for (var l = 0; l < lv; l++){ var np = [pts[0]]; for (var i = 1; i < pts.length; i++){ var p = pts[i - 1], q = pts[i], len = Math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2]), d = len * rough;
          np.push([(p[0] + q[0]) / 2 + (R() - 0.5) * d, (p[1] + q[1]) / 2 + (R() - 0.5) * d * 0.35, (p[2] + q[2]) / 2 + (R() - 0.5) * d], q); } pts = np; rough *= 0.97; } return pts; }   /* tortuous at every scale: sharp zigzags, not a smooth worm */
    function bolt(top, gnd){   /* the main channel, base to ground, and its branches (most die out before the ground) */
      var main = channel(top, gnd, 7, 0.5), br = [], nb = 3 + Math.floor(R() * 5);
      for (var i = 0; i < nb; i++){ var k = Math.floor((0.08 + 0.6 * R()) * (main.length - 1)), s = main[k], dropK = (s[1] - gnd[1]) * (0.25 + 0.45 * R()), ang = R() * 6.283, out = dropK * (0.35 + 0.5 * R());
        var e = [s[0] + Math.cos(ang) * out, s[1] - dropK, s[2] + Math.sin(ang) * out]; br.push({ p: channel(s, e, 5, 0.5), w: 0.45 + 0.25 * R() });
        if (R() < 0.45){ var k2 = Math.floor(br[br.length - 1].p.length * (0.3 + 0.4 * R())), s2 = br[br.length - 1].p[k2], d2 = dropK * 0.35, a2 = ang + (R() - 0.5) * 1.6;
          br.push({ p: channel(s2, [s2[0] + Math.cos(a2) * d2 * 0.8, s2[1] - d2, s2[2] + Math.sin(a2) * d2 * 0.8], 3, 0.4), w: 0.3 }); } }
      return { main: main, br: br }; }
    /* ---- the flashes ---- */
    function strokesCG(){ var n = 2 + Math.floor(R() * 4), S = [], tt = 0; for (var i = 0; i < n; i++){ S.push({ t: tt, a: i ? 0.55 + 0.35 * R() : 1, d: 0.028 + 0.01 * R() }); tt += 0.04 + 0.05 * R(); }
      if (R() < 0.4) S[S.length - 1].cc = 0.12 + 0.12 * R(); return S; }   /* continuing current on the last stroke */
    function strokesIC(){ var n = 4 + Math.floor(R() * 7), S = [], dur = 0.25 + 0.65 * R(); for (var i = 0; i < n; i++) S.push({ t: (i / n) * dur + R() * 0.05, a: 0.35 + 0.65 * R(), d: 0.05 + 0.04 * R() }); return S; }
    function pickCell(mature){ var C = (SC.cells || []).filter(function(c){ return !mature || c.mature; }); if (!C.length) C = SC.cells || []; return C.length ? C[Math.floor(R() * C.length)] : { x: 0, z: 30, R: 6 }; }
    function makeCG(at){ var c = at || pickCell(true), base = SC.base || 1.3, a = R() * 6.283, rr = (at ? 0 : c.R * 0.55 * Math.sqrt(R()));
      var gx = c.x + Math.cos(a) * rr, gz = c.z + Math.sin(a) * rr, top = [gx + (R() - 0.5) * 1.2, base + 0.2, gz + (R() - 0.5) * 1.2], gnd = [gx, 0, gz];
      var b = bolt(top, gnd); st.cg++; return { kind: 'cg', t0: t, S: strokesCG(), B: b, A: [gx, 0, gz], Bp: [top[0], base + 4.5, top[2]], R: 2.6, live: !!at }; }   /* the strike lights its own base and the cloud above it, not only the rain */
    function makeIC(){ var c = pickCell(true), y1 = 3 + R() * 5, y2 = y1 + (R() - 0.3) * 3, r = c.R * 0.45, a = R() * 6.283, b2 = a + (R() - 0.5) * 2;
      st.ic++; return { kind: 'ic', t0: t, S: strokesIC(), A: [c.x + Math.cos(a) * r * R(), y1, c.z + Math.sin(a) * r * R()], Bp: [c.x + Math.cos(b2) * r, Math.max(2.5, y2), c.z + Math.sin(b2) * r], R: 3.2 }; }
    function makeCrawler(){ var c = pickCell(true), dw = SC.dw || [0, -1], len = 8 + R() * 14, side = (R() - 0.5) * 10;   /* downwind, under the anvil */
      st.cr++; var S = strokesIC(); S.forEach(function(s){ s.t *= 1.4; }); return { kind: 'cr', t0: t, S: S, A: [c.x, 9.6, c.z], Bp: [c.x + dw[0] * len + side * dw[1], 9.8, c.z + dw[1] * len - side * dw[0]], R: 3.0, crawl: true }; }
    function amp(e, tt){ var v = 0, br = 0; e.S.forEach(function(s, i){ var dt = tt - s.t; if (dt < 0) return; var k = s.a * Math.exp(-dt / s.d); if (s.cc && dt < 0.4) k = Math.max(k, s.a * s.cc * Math.exp(-dt / 0.15)); v = Math.max(v, k); if (i === 0) br = Math.max(br, s.a * Math.exp(-dt / s.d)); }); return [v, br]; }
    function life(e){ var l = 0; e.S.forEach(function(s){ l = Math.max(l, s.t + s.d * 6 + (s.cc ? 0.6 : 0)); }); return l; }
    function schedule(){ var night = SC.night ? 1 : 0; next = t + (night ? 1.6 + R() * 3 : 3 + R() * 4.5); }
    function spawn(){ var r = R(), e; if (SC.cb === 2) e = r < 0.35 ? makeCG() : makeIC(); else if (SC.cal) e = r < 0.2 ? makeCG() : makeIC(); else e = r < 0.3 ? makeCG() : r < 0.85 ? makeIC() : makeCrawler(); EV.push(e); st.made++; }
    /* ---- draw a polyline in 3-D with a glow ---- */
    function line(pts, w, a, col){ var first = true; ctx.beginPath(); for (var i = 0; i < pts.length; i++){ var q = P(pts[i][0], pts[i][1], pts[i][2]); if (!q){ first = true; continue; } if (first){ ctx.moveTo(q[0], q[1]); first = false; } else ctx.lineTo(q[0], q[1]); }
      ctx.lineWidth = w; ctx.strokeStyle = 'rgba(' + col + ',' + Math.min(1, a).toFixed(3) + ')'; ctx.stroke(); }
    function drawBolt(e, v, vb){ var d = Math.hypot(e.A[0], e.A[2]), att = Math.exp(-d / 150) * (SC.near ? 0.8 : 1) * (SC.night ? 1 : 0.85), soft = 1 + d / 40;   /* far and through rain: dimmer and softer */
      var px = Math.min(1.8, Math.max(0.9, 0.04 / Math.max(d, 1) * W / (2 * tH)));   /* a thin, hard core: 1-2 px whatever the distance (wider read as a glowing worm) */
      ctx.globalCompositeOperation = 'lighter'; ctx.lineCap = 'round'; ctx.lineJoin = 'miter'; ctx.miterLimit = 3;
      if (vb > 0.02) e.B.br.forEach(function(b){ line(b.p, px * 2.6 * Math.min(soft, 2.2), 0.08 * vb * att, '150,175,255'); line(b.p, Math.max(0.6, px * b.w), 0.8 * vb * att, '225,232,255'); });
      line(e.B.main, px * 5 * Math.min(soft, 2.2), 0.1 * v * att, '140,165,255'); line(e.B.main, px * 2, 0.35 * v * att, '200,215,255'); line(e.B.main, px, 1.0 * v * att, '255,255,255');
      var g = P(e.A[0], 0.02, e.A[2]); if (g){ var rr = px * 9 * soft * (0.6 + v); var gr = ctx.createRadialGradient(g[0], g[1], 0, g[0], g[1], rr); gr.addColorStop(0, 'rgba(220,228,255,' + (0.5 * v * att).toFixed(3) + ')'); gr.addColorStop(1, 'rgba(220,228,255,0)'); ctx.fillStyle = gr; ctx.fillRect(g[0] - rr, g[1] - rr, rr * 2, rr * 2); }   /* the attachment glow at the ground */
      ctx.globalCompositeOperation = 'source-over'; }
    return {
      scene: function(s){ SC = s; if (s.W){ W = s.W; H = s.H; } if (s.tH) tH = s.tH; cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = W + 'px'; cv.style.height = H + 'px'; cam(); EV.length = 0; LQ.length = 0; next = t + 1.5 + R() * 2; },
      live: function(x, z){ if (LQ.length < 4) LQ.push([x, z]); },
      frame: function(nowMs){ t = nowMs / 1000; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H); if (!SC){ u.I = 0; u.G = 0; return; }
        if (t >= next){ spawn(); schedule(); }
        if (LQ.length && !EV.some(function(e){ return e.live && t - e.t0 < 1.2; })){ var q = LQ.shift(); EV.push(makeCG({ x: q[0], z: q[1], R: 0 })); st.live++; st.made++; }   /* a real strike, at its true direction */
        var best = null, bv = 0, G = 0;
        for (var i = EV.length - 1; i >= 0; i--){ var e = EV[i], tt = t - e.t0; if (tt > life(e)){ EV.splice(i, 1); continue; }
          var a = amp(e, tt), v = a[0]; if (e.crawl){ var f = Math.min(1, tt / (life(e) * 0.8)); e.Acur = [e.A[0] + (e.Bp[0] - e.A[0]) * f * 0.5, e.A[1], e.A[2] + (e.Bp[2] - e.A[2]) * f * 0.5]; e.Bcur = [e.A[0] + (e.Bp[0] - e.A[0]) * f, e.Bp[1], e.A[2] + (e.Bp[2] - e.A[2]) * f]; }   /* the crawler spreads along the anvil */
          if (e.kind === 'cg' && v > 0.01) drawBolt(e, v, a[1]);
          G = Math.max(G, v * (e.kind === 'cg' ? 1 : 0.7)); if (v > bv){ bv = v; best = e; } }
        if (best){ u.A = best.Acur || best.A; u.B = best.Bcur || best.Bp; u.R = best.R; u.I = bv; } else u.I = 0;
        u.G = G; u.rain = G; if (G > 0.3) fastUntil = t + 0.07; u.fast = t < fastUntil; },   /* fast blending only on the stroke peaks: left on through a whole flash it showed the raw march grain */
      u: function(){ return u; },
      stats: function(){ return { made: st.made, cg: st.cg, ic: st.ic, crawl: st.cr, live: st.live, active: EV.length, I: u.I }; },
      destroy: function(){ EV.length = 0; SC = null; }
    };
  };
})();
