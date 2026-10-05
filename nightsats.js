/* bvNightSats -- the satellites over the location, live, for the clear-night hero (2026-10-05, user: "could the clear night
   hero include satellites floating through that are above the location live" -> "yes build the clear night lab").
   WHAT SHOWS: what a person standing there could see. A satellite is visible only while IT is sunlit and the OBSERVER is in
   darkness, so they come out in the hours after dusk and before dawn, fade out mid-sky as they cross into Earth's shadow,
   and a midnight sky often has none -- that is true, not a fault.
   HOW: SGP4 (satellite.js 5.0.0, cdnjs) in a Web Worker, so the page thread only draws. Each second the worker propagates
   every object at the lab time t and t + span, keeps what is above the horizon, and returns look angles, sunlit fraction
   and an estimated magnitude for both ends; the page interpolates between them, so the motion is smooth and true to its
   angular speed (the ISS takes ~5 minutes to cross).
   BRIGHTNESS is an ESTIMATE (shown as derived): a standard magnitude per object class at 1000 km and half phase,
   moved by range (5 log10 r/1000) and by a diffuse-sphere phase function. Sunlit: Earth's shadow as a cylinder, softened
   over ~40 km so they fade rather than blink out. Sun: low-precision solar position (Meeus), fine for a shadow test.
   PROJECTION: 'south' = a 180 deg panorama facing south (east at the left edge, west at the right), 'full' = 360 deg with
   south at the centre; elevation 0 at the horizon line (the planet bars) to 90 at the top.
   Data: CelesTrak GP (U.S. Space Force catalogue), baked by bake_night_tle.sh into _tle_night.js (CelesTrak sends no CORS).
   Usage: var s = bvNightSats(canvas, { W, H, lat, lon, horizon, top, view, lim, labels, tle, lib });
          s.set({ time: ms, speed, view, lim, labels, sunAlt }); s.list(); s.stats(); s.pick(x, y); s.destroy();
   Lab: _cloudlab/clear_night_lab.html (the master copy of this engine -- edit there, copy here). LIVE from 2026-10-05:
   the controller at the end of this file (window._bvSatsSync), called by _updateHeroWx, runs it over the clear-night hero. */
(function(){
  var WORKER = function(){
    var sats = [], R2D = 180 / Math.PI, RE = 6371;
    function stdMag(name, group, nm){
      if (/^ISS \(ZARYA\)/.test(name)) return -1.3;
      if (/TIANHE|^CSS/.test(name)) return 0.0;
      if (/^HST$|HUBBLE/.test(name)) return 2.2;
      if (/\[DTC\]/.test(name)) return 4.8;                            /* direct-to-cell: big, but they LIVE low (~360 km) -- not a train */
      if (group === 'starlink') return nm > 15.7 ? 3.6 : 5.6;          /* a fresh launch low and raising its orbit is brighter (the trains) */
      return 4.2;
    }
    function sunDir(d){
      var n = d / 864e5 + 2440587.5 - 2451545.0, rad = Math.PI / 180;
      var L = (280.46 + 0.9856474 * n) % 360, g = ((357.528 + 0.9856003 * n) % 360) * rad;
      var lam = (L + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * rad, eps = (23.439 - 0.0000004 * n) * rad;
      return [Math.cos(lam), Math.cos(eps) * Math.sin(lam), Math.sin(eps) * Math.sin(lam)];
    }
    function look(s, date, gd, obsEci, sun){
      var pv = satellite.propagate(s.rec, date); if (!pv || !pv.position) return null;
      var r = pv.position, gm = satellite.gstime(date), la = satellite.ecfToLookAngles(gd, satellite.eciToEcf(r, gm));
      var el = la.elevation * R2D; if (el < -3) return { el: el };
      var sd = r.x * sun[0] + r.y * sun[1] + r.z * sun[2], px = r.x - sd * sun[0], py = r.y - sd * sun[1], pz = r.z - sd * sun[2];
      var lit = sd >= 0 ? 1 : Math.max(0, Math.min(1, (Math.sqrt(px * px + py * py + pz * pz) - RE) / 40 + 0.5));
      var ox = obsEci.x - r.x, oy = obsEci.y - r.y, oz = obsEci.z - r.z, ol = Math.sqrt(ox * ox + oy * oy + oz * oz) || 1;
      var cphi = Math.max(-1, Math.min(1, (ox * sun[0] + oy * sun[1] + oz * sun[2]) / ol)), phi = Math.acos(cphi);
      var F = Math.max(1e-4, Math.sin(phi) + (Math.PI - phi) * Math.cos(phi));          /* diffuse sphere, normalised to half phase */
      var mag = s.std + 5 * Math.log10(la.rangeSat / 1000) - 2.5 * Math.log10(F);
      return { az: la.azimuth * R2D, el: el, lit: lit, mag: mag, rng: la.rangeSat, alt: Math.sqrt(r.x * r.x + r.y * r.y + r.z * r.z) - RE };
    }
    onmessage = function(e){
      var m = e.data;
      if (m.lib) importScripts(m.lib);
      if (m.tle){
        if (!m.append) sats = [];
        m.tle.forEach(function(t){
          var nm = parseFloat(t[2].slice(52, 63));
          try { var rec = satellite.twoline2satrec(t[1], t[2]); if (!rec.error) sats.push({ name: t[0], group: t[3], rec: rec, std: stdMag(t[0], t[3], nm) }); } catch (_){}
        });
        postMessage({ ready: sats.length, append: !!m.append });
        return;
      }
      if (m.t){
        var t0 = performance.now(), d0 = new Date(m.t), d1 = new Date(m.t + m.span * 1000);
        var gd = { latitude: m.lat * Math.PI / 180, longitude: m.lon * Math.PI / 180, height: 0.01 };
        var oe0 = satellite.ecfToEci(satellite.geodeticToEcf(gd), satellite.gstime(d0)), oe1 = satellite.ecfToEci(satellite.geodeticToEcf(gd), satellite.gstime(d1));
        var s0 = sunDir(+d0), s1 = sunDir(+d1), out = [];
        for (var i = 0; i < sats.length; i++){
          var a = look(sats[i], d0, gd, oe0, s0); if (!a || a.el < -3) continue;
          var b = look(sats[i], d1, gd, oe1, s1); if (!b || b.az == null) continue;
          out.push([i, a.az, a.el, b.az, b.el, a.mag, b.mag, a.lit, b.lit, a.alt, a.rng]);
        }
        postMessage({ t: m.t, span: m.span, rows: out, names: m.wantNames ? sats.map(function(s){ return [s.name, s.group]; }) : null, ms: performance.now() - t0, n: sats.length });
      }
    };
  };

  window.bvNightSats = function(cv, o){
    o = Object.assign({ W: 1180, H: 620, lat: 40.78, lon: -73.97, horizon: 480, top: 20, view: 'south', lim: 5, labels: true, speed: 1, sunAlt: -20,
                        lib: 'https://cdnjs.cloudflare.com/ajax/libs/satellite.js/5.0.0/satellite.min.js', tle: window.NIGHT_TLE || [] }, o || {});
    var ctx = cv.getContext('2d'), dpr = Math.min(2, window.devicePixelRatio || 1);
    var url = URL.createObjectURL(new Blob(['(' + WORKER.toString() + ')()'], { type: 'text/javascript' }));
    var wk = new Worker(url), ready = false, names = null, frame = null, next = null, alive = true, raf = 0, timer = 0, st = { ms: 0, n: 0, shown: 0, rows: 0, draw: 0 };
    var labT = o.time || Date.now(), realT = performance.now();
    function dims(){ cv.width = Math.round(o.W * dpr); cv.height = Math.round(o.H * dpr); cv.style.width = o.W + 'px'; cv.style.height = o.H + 'px'; }
    dims();
    function labNow(){ return labT + (performance.now() - realT) * o.speed; }
    wk.onmessage = function(e){
      var m = e.data;
      if (m.ready != null){ ready = true; st.n = m.ready; names = null; ask(true); return; }   /* (more orbits: re-send the names) */
      if (m.names) names = m.names;
      st.ms = m.ms; st.rows = m.rows.length;
      /* the new pair takes over from the moment it was asked for */
      frame = m;
    };
    wk.postMessage({ lib: o.lib, tle: o.tle });
    function ask(first){
      if (!ready || !alive) return;
      var span = Math.max(1, o.speed) * 1.0;
      wk.postMessage({ t: labNow(), span: span, lat: o.lat, lon: o.lon, wantNames: !names || first });
    }
    timer = setInterval(function(){ ask(false); }, 1000);

    function proj(az, el){
      var x;
      if (o.view === 'full'){ var a = ((az - 180 + 540) % 360) - 180; x = o.W / 2 + a / 180 * (o.W / 2); }
      else { if (az < 90 || az > 270) return null; x = (az - 90) / 180 * o.W; }
      return [x, o.horizon - Math.max(0, el) / 90 * (o.horizon - o.top)];
    }
    function lerpAz(a, b, f){ var d = ((b - a + 540) % 360) - 180; return (a + d * f + 360) % 360; }
    var shown = [];
    function draw(){
      raf = 0; if (!alive) return;
      var t0 = performance.now();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, o.W, o.H); shown = [];
      if (frame && names){
        var f = Math.max(0, Math.min(1.5, (labNow() - frame.t) / (frame.span * 1000)));
        /* the sky's own brightness sets how faint a satellite can be seen: none in daylight, the limit rising to the
           chosen one through nautical into astronomical twilight */
        var limEff = o.lim - Math.max(0, (o.sunAlt + 15) * 0.55);
        /* brightest first, and a station's modules and docked craft (tracked as their own objects, in the same spot) merge
           into the station: any 'stations' object within 1 deg of one already drawn is skipped */
        var rows = frame.rows.slice().sort(function(a, b){ return a[5] - b[5]; }), st0 = [];
        rows.forEach(function(r){
          var az = lerpAz(r[1], r[3], f), el = r[2] + (r[4] - r[2]) * f, mag = r[5] + (r[6] - r[5]) * f, lit = r[7] + (r[8] - r[7]) * f;
          if (el < 0 || lit <= 0.01 || mag > limEff) return;
          if (names[r[0]][1] === 'stations'){ if (st0.some(function(q){ return Math.abs(((az - q[0] + 540) % 360) - 180) < 1 && Math.abs(el - q[1]) < 1; })) return; st0.push([az, el]); }
          var p = proj(az, el); if (!p) return;
          var a = Math.max(0.12, Math.min(1, (limEff - mag) / 3 + 0.25)) * lit * Math.min(1, el / 3);
          var rad = Math.max(0.7, Math.min(3.0, 2.5 - 0.32 * mag)), nm = names[r[0]][0], warm = /^ISS \(ZARYA\)|TIANHE|^CSS/.test(nm);
          if (mag < 1.5){
            var g = ctx.createRadialGradient(p[0], p[1], 0, p[0], p[1], rad * 4);
            g.addColorStop(0, 'rgba(255,248,230,' + (0.45 * a).toFixed(3) + ')'); g.addColorStop(1, 'rgba(255,248,230,0)');
            ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p[0], p[1], rad * 4, 0, 6.2832); ctx.fill();
          }
          ctx.fillStyle = warm ? 'rgba(255,244,214,' + a.toFixed(3) + ')' : 'rgba(232,238,255,' + a.toFixed(3) + ')';
          ctx.beginPath(); ctx.arc(p[0], p[1], rad, 0, 6.2832); ctx.fill();
          shown.push({ x: p[0], y: p[1], name: nm, group: names[r[0]][1], mag: mag, el: el, az: az, alt: r[9], rng: r[10], lit: lit });
          if (o.labels && mag < 2.5 && names[r[0]][1] !== 'starlink'){   /* names for the stations and named bright objects; a Starlink's catalogue name is clutter */
            ctx.font = '600 9px system-ui, sans-serif'; ctx.fillStyle = 'rgba(220,228,255,' + (0.6 * a).toFixed(3) + ')';
            ctx.fillText(nm.replace(/ \(.*\)$/, '').replace(/^ISS$/, 'ISS'), p[0] + rad + 5, p[1] + 3);
          }
        });
      }
      st.shown = shown.length; st.draw = st.draw * 0.9 + (performance.now() - t0) * 0.1;
      raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);

    return {
      set: function(p){
        if (p.time != null){ labT = p.time; realT = performance.now(); frame = null; }
        if (p.speed != null){ labT = labNow(); realT = performance.now(); o.speed = p.speed; }
        ['view', 'lim', 'labels', 'sunAlt', 'lat', 'lon'].forEach(function(k){ if (p[k] != null) o[k] = p[k]; });
        if (p.W || p.H || p.horizon || p.top){ Object.assign(o, p); dims(); }
        if (p.time != null || p.speed != null || p.lat != null) ask(false);
      },
      /* more orbits after the first batch (the site loads the small core set, then -- desktop -- the rest of Starlink) */
      add: function(rows){ if (rows && rows.length) wk.postMessage({ tle: rows, append: true }); },
      now: labNow,
      list: function(){ return shown.slice().sort(function(a, b){ return a.mag - b.mag; }); },
      pick: function(x, y){ var best = null, bd = 14 * 14; shown.forEach(function(s){ var d = (s.x - x) * (s.x - x) + (s.y - y) * (s.y - y); if (d < bd){ bd = d; best = s; } }); return best; },
      stats: function(){ return { ready: ready, objects: st.n, aboveHorizon: st.rows, shown: st.shown, workerMs: st.ms, drawMs: st.draw }; },
      destroy: function(){ alive = false; clearInterval(timer); if (raf) cancelAnimationFrame(raf); wk.terminate(); URL.revokeObjectURL(url); }
    };
  };
})();

/* THE CLEAR-NIGHT HERO'S SATELLITES ON THE SITE (2026-10-05, user: "continue with the clear night satellites").
   _updateHeroWx calls window._bvSatsSync(state, #hero-wx) at its end, every time it runs (next to the flock's sync).
   Made for the CLEAR-NIGHT hero of TODAY (the live sky -- other days' nights are a forecast), removed for every other
   state. Own canvas, #hero-sats, in the sky bar right after #hero-wx: over the galaxy art, under the moon, readout and
   bars. Horizon = top of #today-tl-planet-tracks, top edge = bottom of #conditions-briefing.
   Orbits: cdn.bluishvoid.com/sats/core.json (stations, brightest objects, Starlink trains and direct-to-cell; ~56 KB) and,
   desktop only, sats/starlink.json (the other ~10k Starlinks; ~0.5 MB), both baked daily by sats-night.yml, fetched
   only when this hero shows, with an hourly query key so the Cloudflare edge can't pin a stale day.
   Off: lite mode, reduced motion, no Worker. Waits for the loading curtain. The sun's altitude (darkness gates what
   shows) and the location refresh every 30 s; a location switch re-aims the worker. */
(function(){
  var C = { s: null, cv: null, wait: 0, tick: 0, last: null, gw: 0, gh: 0, ghz: 0, gtop: 0 };
  function off(){ if (C.s){ try { C.s.destroy(); } catch(e){} C.s = null; } if (C.cv && C.cv.parentNode) C.cv.parentNode.removeChild(C.cv); C.cv = null;
    if (C.tick){ clearInterval(C.tick); C.tick = 0; } }
  function reduced(){ try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch(e){ return false; } }
  function phone(){ try { return window.matchMedia('(max-width: 768px)').matches; } catch(e){ return false; } }
  function url(f){ return 'https://cdn.bluishvoid.com/sats/' + f + '.json?h=' + new Date().toISOString().slice(0, 13); }
  function sunAlt(){ try { return _sunAltNow(LOCATION.lat, LOCATION.lon); } catch(e){ return -20; } }
  function geom(sb, hw){
    var sr = sb.getBoundingClientRect(), W = Math.round(sb.clientWidth || sr.width), H = Math.round(hw.offsetHeight || parseInt(hw.style.height, 10) || 0);
    var hz = Math.round(H * 0.78), pt = document.getElementById('today-tl-planet-tracks');
    if (pt){ var pr = pt.getBoundingClientRect(); if (pr.height > 0){ var v = Math.round(pr.top - sr.top - 6); if (v > H * 0.3 && v < H) hz = v; } }
    var top = 20, bf = sb.querySelector('#conditions-briefing');
    if (bf){ var br = bf.getBoundingClientRect(); if (br.height > 0){ var v2 = Math.round(br.bottom - sr.top + 12); if (v2 > 0 && v2 < hz - 80) top = v2; } }
    return { W: W, H: H, horizon: hz, top: top };
  }
  function load(f){ return fetch(url(f)).then(function(r){ if (!r.ok) throw new Error(r.status); return r.json(); }).then(function(j){ return j && j.rows || []; }); }
  window._bvSatsSync = function(st, hw){
    try {
      var sb = hw && hw.parentNode && hw.parentNode.classList && hw.parentNode.classList.contains('today-tl-sky-bar') ? hw.parentNode : null;
      if (st !== 'clear-night' || !sb || window.BV_LITE || reduced() || (window._tlDayOffset || 0) !== 0 || !window.LOCATION || !window.Worker || typeof window.bvNightSats !== 'function'){ off(); return; }
      if (document.getElementById('site-loading-screen')){
        if (!C.wait) C.wait = setTimeout(function(){ C.wait = 0; window._bvSatsSync(C.last, document.getElementById('hero-wx')); }, 400);
        C.last = st; return;
      }
      C.last = st;
      if (!C.cv){ C.cv = document.createElement('canvas'); C.cv.id = 'hero-sats'; C.cv.style.cssText = 'position:absolute;left:0;top:0;z-index:0;pointer-events:none;'; }
      if (C.cv.parentNode !== sb || C.cv.previousSibling !== hw) sb.insertBefore(C.cv, hw.nextSibling);
      var g = geom(sb, hw); if (g.W < 40 || g.H < 60) return;
      var L = window.LOCATION;
      if (!C.s){
        var ph = phone();
        C.gw = g.W; C.gh = g.H; C.ghz = g.horizon; C.gtop = g.top;
        C.s = bvNightSats(C.cv, { W: g.W, H: g.H, horizon: g.horizon, top: g.top, lat: L.lat, lon: L.lon, view: 'south', lim: ph ? 4.0 : 4.6, labels: true, speed: 1, sunAlt: sunAlt(), tle: [] });
        var mine = C.s;
        load('core').then(function(rows){ if (C.s === mine) mine.add(rows); if (!ph) return load('starlink').then(function(r2){ if (C.s === mine) mine.add(r2); }); }).catch(function(){});
        C.tick = setInterval(function(){ if (C.s && window.LOCATION) C.s.set({ sunAlt: sunAlt(), lat: LOCATION.lat, lon: LOCATION.lon }); }, 30000);
      } else {
        var p = { sunAlt: sunAlt() };
        if (C.s && (L.lat !== C.lat || L.lon !== C.lon)){ p.lat = L.lat; p.lon = L.lon; }
        if (g.W !== C.gw || g.H !== C.gh || g.horizon !== C.ghz || g.top !== C.gtop){ p.W = g.W; p.H = g.H; p.horizon = g.horizon; p.top = g.top; C.gw = g.W; C.gh = g.H; C.ghz = g.horizon; C.gtop = g.top; }
        C.s.set(p);
      }
      C.lat = L.lat; C.lon = L.lon;
    } catch(e){}
  };
  window.addEventListener('resize', function(){ var h = document.getElementById('hero-wx'); if (C.s && h) window._bvSatsSync(C.last, h); });
  /* for checking from the console: the running engine (stats(), list(), set({ time })) or null */
  window._bvSats = function(){ return C.s; };
})();
