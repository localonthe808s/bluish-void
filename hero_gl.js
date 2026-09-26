/* bvHeroGL -- the live-weather hero's CLOUDS on the GPU (2026-09-26, user: "update them all").
   The hero's SVG clouds (blurred ellipses under a fractal filter) are replaced by the renderer the front scenes and the
   golden-hour sky use: bvCloudGL's lit, textured decks and towers, and bvSky2 for fair-weather cumulus and fog. The SVG
   keeps what animates -- rain streaks, snow, sleet, hail, lightning -- drawn over this with _HERO_NOCLOUD set, so the
   drops still fall from the cloud base. Rendered once per scene (static), so it costs nothing per frame.
   Scene units: 393 across (a phone's width), y UP from the bottom; `base` is where the precipitation spawns. */
(function(){
  function rng(seed){ var s = seed >>> 0 || 1; return function(){ s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
  var OFF = [9000, 9001, -3, -2];
  /* per state: how dark the underside, how low and deep the deck, whether a tower rises through it */
  var LOOK = {
    'drizzle':    { shd: [.60, .64, .70], lit: [.96, .97, 1.0], rows: 3, rMul: .9,  strat: .8, scud: 4 },
    'rain':       { shd: [.46, .51, .59], lit: [.90, .92, .96], rows: 4, rMul: 1,   strat: .6, scud: 7 },
    'rain-heavy': { shd: [.34, .38, .46], lit: [.82, .85, .90], rows: 5, rMul: 1.1, strat: .3, scud: 10, tower: .75 },
    'freezing':   { shd: [.52, .57, .65], lit: [.92, .94, .98], rows: 4, rMul: .95, strat: .7, scud: 5 },
    'snow':       { shd: [.66, .70, .77], lit: [1.0, 1.0, 1.02], rows: 4, rMul: 1,  strat: .9, scud: 3 },
    'sleet':      { shd: [.56, .61, .69], lit: [.94, .95, .99], rows: 4, rMul: .95, strat: .7, scud: 5 },
    'storm':      { shd: [.28, .31, .39], lit: [.86, .88, .93], rows: 4, rMul: 1.1, strat: .2, scud: 9, tower: 1 },
    'storm-hail': { shd: [.26, .29, .37], lit: [.88, .89, .94], rows: 4, rMul: 1.15, strat: .15, scud: 9, tower: 1.12 },
    'overcast':   { shd: [.54, .58, .65], lit: [.93, .94, .97], rows: 6, rMul: 1.05, strat: 1, scud: 0, full: 1 }
  };
  window.bvHeroGL = function(ctx, o){
    if (!window.bvCloudGL || !bvCloudGL.ok()) return false;
    var W = 393, H = Math.round(393 * o.H / o.W), st = o.state, night = !!o.night, R = rng(o.seed || 7);
    var ppu = Math.min(3, Math.max(1.5, o.W / 393 * (o.dpr || 1) * 0.75));
    ctx.save(); ctx.setTransform(o.W / W * (o.dpr || 1), 0, 0, o.W / W * (o.dpr || 1), 0, 0);
    try {
      if (st === 'partly' || st === 'fog'){
        if (!window.bvSky2){ return false; }
        var types = st === 'partly' ? [{ genus: 'Cumulus', species: 'mediocris', layer: 'low', cover: 38 }] : [{ genus: 'Fog', species: 'moderate', layer: 'low', cover: 100 }];
        var ok2 = bvSky2(ctx, { W: W, H: H, hz: 6, sa: night ? -20 : 40, types: types, ppu: ppu, dens: W / 220 });
        if (ok2 && night){ ctx.save(); ctx.globalCompositeOperation = 'source-atop'; ctx.fillStyle = st === 'fog' ? 'rgba(120,135,165,.45)' : 'rgba(70,90,135,.42)'; ctx.fillRect(0, 0, W, H); ctx.restore(); }   /* moonlit: cool blue-grey, not the dark brown the night palette gave */
        return ok2;
      }
      var L = LOOK[st]; if (!L) return false;
      var base = o.baseUp == null ? H * 0.42 : o.baseUp * W / o.W;   /* where the drops spawn, in scene units, from the bottom */
      var shd = night ? L.shd.map(function(v){ return v * 0.32; }) : L.shd, lit = night ? [0.42, 0.46, 0.58] : L.lit;
      var common = { W: W, H: H, ppu: ppu, t: (o.seed || 7) * 3, night: night ? 1 : 0, sunDir: night ? [0.2, 0.95] : [-0.25, 0.97], sunCol: lit, shdCol: shd, ground: 0, band: OFF, ns: 0.62 };
      /* THE DECK: rows of lobes from the base up past the top, bigger and flatter with height, so it reads as one ceiling
         seen from below -- lumpy undersides, a lit upper body */
      var sc = function(v, a){ return 'rgba(' + Math.round(v[0] * 255) + ',' + Math.round(v[1] * 255) + ',' + Math.round(v[2] * 255) + ',' + a + ')'; };
      var b0 = L.full ? H * 0.34 : base, P = [];
      if (L.full){
        /* OVERCAST: the ceiling in RANKS receding toward the horizon, as the old SVG deck was built -- the nearest rank high,
           big and lumpy, each further one lower, smaller and hazier, a thin lighter seam of sky-glow between them. Each rank is
           its own call (a separate layer at its own depth) */
        var ranks = [[H + 10, H * 0.56, 30, 1], [H * 0.6, H * 0.42, 20, 0.92], [H * 0.45, H * 0.31, 13, 0.85], [H * 0.33, H * 0.24, 8, 0.78]];
        ranks.forEach(function(rk, ri){ var Q = [], rr0 = rk[2] * L.rMul;
          for (var yy = rk[0]; yy > rk[1]; yy -= rr0 * 0.8) for (var xx = -rr0 * 0.5 + R() * rr0; xx < W + rr0; xx += rr0 * (1.0 + 0.5 * R())) Q.push([xx, yy + (R() - 0.5) * rr0 * 0.5, rr0 * (0.7 + 0.5 * R()), 0.85 + 0.15 * R()]);
          for (var xb2 = R() * rr0; xb2 < W + rr0; xb2 += rr0 * (0.8 + 0.6 * R())) Q.push([xb2, rk[1] + rr0 * 0.1 - R() * R() * rr0 * 0.6, rr0 * (0.45 + 0.35 * R()), 0.8]);   /* the rank's torn underside */
          Q.sort(function(a, b){ return b[3] - a[3]; });
          var fade = rk[3];
          /* distance flattens and hazes a rank: less relief, less contrast (lit and shade both drift to the horizon's grey) */
          var hz = 1 - fade, hzc = night ? [0.2, 0.22, 0.27] : [0.6, 0.63, 0.68];
          bvCloudGL(ctx, Object.assign({}, common, { puffs: Q.slice(0, 48), lean: 0, strat: Math.min(1, hz * 4.5), base: 0, h: 1, hw: 1, cx: 0, dens: 1, ns: ri === 0 ? 0.5 : 0.62 * (34 / rk[2]) * 0.5,
            sunCol: lit.map(function(v, ci){ return v + (hzc[ci] + 0.12 - v) * hz * 3; }), shdCol: shd.map(function(v, ci){ return v + (hzc[ci] - v) * hz * 3; }) })); });
        P = null;
      } else {
        /* THE RAIN CLOUD, as the hero has always framed it: ONE great mass across the middle, its base where the drops start --
           a flat-ish, lumpy underside, heaped and lit above, the edges torn -- now drawn as a real cloud */
        var tall = Math.max(1, H / 220), cx0 = W * 0.5, hw0 = W * (0.36 + 0.05 * (L.rMul - 1) * 4) * (tall > 1.5 ? 1.25 : 1), ht = (L.tower ? 70 : 52) * L.rMul * tall;   /* a tall phone panel: the mass grows with it */
        for (var rr = 0; rr < 5; rr++){ var f2 = rr / 4, y2 = b0 + 6 + ht * f2, half = hw0 * Math.sqrt(1 - f2 * f2 * 0.85), r2 = (15 + 10 * (1 - Math.abs(f2 - 0.4))) * L.rMul * Math.sqrt(tall);
          for (var x2 = cx0 - half + R() * r2 * 0.5; x2 < cx0 + half; x2 += r2 * (0.9 + 0.5 * R())) P.push([x2, y2 + (R() - 0.5) * r2 * 0.6, r2 * (0.75 + 0.5 * R()), 0.85 + 0.15 * R()]); }
        for (var xh = cx0 - hw0 * 1.05; xh < cx0 + hw0 * 1.05; xh += 16 + R() * 18) P.push([xh, b0 + 3 - R() * R() * 12, 7 + R() * 9, 0.7 + 0.25 * R()]);   /* the torn, uneven base */
      }
      if (P){ P.sort(function(a, b){ return b[3] - a[3]; }); P = P.slice(0, 48);
      bvCloudGL(ctx, Object.assign({}, common, { puffs: P, lean: 0, strat: 0, base: 0, h: 1, hw: 1, cx: 0, dens: 1, ns: 0.62 })); }
      /* seen from below, a rain cloud is darkest at its base: tone the cloud pixels only */
      var yB = H - b0, g1 = ctx.createLinearGradient(0, yB - (L.full ? H : 90), 0, yB + 30);
      g1.addColorStop(0, sc(shd, 0)); g1.addColorStop(1, sc(shd.map(function(v){ return v * 0.75; }), L.full ? 0.22 : 0.45));
      if (!L.full){ ctx.save(); ctx.globalCompositeOperation = 'source-atop'; ctx.fillStyle = g1; ctx.fillRect(0, 0, W, yB + 40); ctx.restore(); }   /* past the hanging lobes: a lighter lip under the toned base read as a line */
      /* FAR CLOUDS, low on either side (the old scene's far precip): small separate masses, hazier */
      if (!L.full) [[0.1, 0.8], [0.9, 0.85], [0.03, 0.55], [0.97, 0.6]].forEach(function(fc, i){ var Q = [], fx = W * fc[0], fy = b0 * fc[1] - 6, fr = 8 + R() * 5;
        for (var m = 0; m < 7; m++){ var mu = (m - 3) / 3; Q.push([fx + mu * fr * 2.4 + (R() - 0.5) * 5, fy + (1 - mu * mu) * fr * 0.9 + R() * 3, fr * (0.75 + 0.45 * R()) * (1 - 0.3 * Math.abs(mu)), 0.85]); }    /* a small heaped cloud, not a lens */
        bvCloudGL(ctx, Object.assign({}, common, { puffs: Q, lean: 0, strat: 0, base: 0, h: 1, hw: 1, cx: 0, dens: 0.8, ns: 0.62, sunCol: lit.map(function(v){ return v * 0.94; }) })); });
      /* A TOWER through it for the heavy states: the storm's own body, rising off the top */
      if (L.tower){ bvCloudGL(ctx, Object.assign({}, common, { cx: W * 0.5, base: base - 4, h: (H - base) * 1.3, hw: 46 * L.tower, lean: 0.3, anvil: 0, rain: 0, rag: 3.5, dens: 1, ns: 0.5 })); }
      return true;
    } finally { ctx.restore(); }
  };
})();
