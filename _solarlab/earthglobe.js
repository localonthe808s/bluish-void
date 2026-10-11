/* BVGlobe: the Earth as it really faces the Sun at a given moment, drawn from one day of NASA DSCOVR/EPIC photos stitched
   into a map (cdn earth/globe/epic.jpg, baked by _maplab/epic_globe_bake.py). User 2026-10-11: "can the earth
   realistically spin as it would for the tonight and earth view".

   The view is EPIC's own: from the sunward side, centred on the subsolar point (declination, and the longitude where it is
   noon), so the disc is the day face and turns west 15 degrees an hour, the way the photos do over a day. Each lab drives
   it with its own clock (Earth View's timeline, TONIGHT's night scrubber), so paused it shows the true face for that
   minute and played it spins at the played rate.

   POLE MODE (o.pole, 2026-10-11, user: "in earth view were looking at the earth from the poles right? that wouldnt be how
   the earth would look at this angle"): both labs draw space from ABOVE the north pole, so the globe is the northern
   hemisphere seen from over the pole, the noon meridian pointed at the drawn Sun (set(ms, sunAngleDeg), maths angle,
   counter-clockwise, y up); east runs counter-clockwise, the way Earth turns seen from the north. onframe also gets the
   pole-view centroid {lat:90, lon} that the labs' orthographic pin code expects.

   BVGlobe.make({ size, cx, r, onframe(dataUrl, sub), pole }) -> { set(ms[, sunAngleDeg]) }. cx, r: disc centre and radius as fractions of the
   square canvas, matching the EPIC image geometry each lab already uses. Renders at most ~15 times a second and only when
   the face has turned by 0.2 degrees or more. Falls back silently (the lab keeps its EPIC still) if the map cannot load. */
(function(){
  var D = Math.PI / 180;
  var SRC = ['https://cdn.bluishvoid.com/earth/globe/epic.jpg', 'globe/epic.jpg'];
  var TEX = null, TW = 0, TH = 0, waiting = [];
  function loadTex(i){
    if (i >= SRC.length) return;
    var im = new Image(); im.crossOrigin = 'anonymous';
    im.onload = function(){ try {
        var c = document.createElement('canvas'); c.width = im.naturalWidth; c.height = im.naturalHeight;
        var g = c.getContext('2d'); g.drawImage(im, 0, 0); TEX = g.getImageData(0, 0, c.width, c.height).data; TW = c.width; TH = c.height;
        waiting.forEach(function(f){ f(); }); waiting = [];
      } catch(e){ loadTex(i + 1); } };
    im.onerror = function(){ loadTex(i + 1); };
    im.src = SRC[i] + (i ? '' : '?d=' + new Date().toISOString().slice(0, 10));
  }
  /* the subsolar point: low-precision Sun (good to ~0.01 deg) and Greenwich sidereal time */
  function subsolar(ms){
    var n = ms / 86400000 + 2440587.5 - 2451545;
    var L = (280.460 + 0.9856474 * n) % 360, g = (357.528 + 0.9856003 * n) * D;
    var lam = (L + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * D, eps = (23.439 - 4e-7 * n) * D;
    var dec = Math.asin(Math.sin(eps) * Math.sin(lam)), ra = Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam));
    var gmst = (280.46061837 + 360.98564736629 * n) % 360;
    var lon = ((ra / D - gmst) % 360 + 540) % 360 - 180;
    return { lat: dec / D, lon: lon };
  }
  function make(o){
    var N = o.size || 512, cx = (o.cx == null ? 0.5 : o.cx) * N, rr = (o.r || 0.392) * N;
    var cv = document.createElement('canvas'); cv.width = cv.height = N; var g = cv.getContext('2d');
    var img = g.createImageData(N, N), px = img.data;
    var grid = null, gridLat = null, idx = [], lastLon = null, lastLat = null, want = null, wantAng = 0, busy = false, lastT = 0, POLE = !!o.pole;
    /* per disc pixel: latitude and longitude offset for the current centre latitude (changes slowly: rebuild at 0.25 deg) */
    function build(lat0){
      if (POLE){ gridLat = lat0; idx = []; grid = [];   /* from over the north pole: rho = cos(lat), angle = longitude offset */
        for (var y = 0; y < N; y++) for (var x = 0; x < N; x++){ var u = (x + 0.5 - cx) / rr, v = (cx - y - 0.5) / rr, rho = Math.sqrt(u * u + v * v); if (rho >= 1) continue;
          var lat = Math.acos(rho), th = Math.atan2(v, u) / D, shade = 0.72 + 0.28 * Math.pow(Math.sqrt(1 - rho * rho), 0.6);
          idx.push((y * N + x) * 4); grid.push(((90 - lat / D) / 180 * TH) | 0, th, shade); }
        return; }
      gridLat = lat0; var p0 = lat0 * D, sp = Math.sin(p0), cp = Math.cos(p0); idx = []; grid = [];
      for (var y = 0; y < N; y++) for (var x = 0; x < N; x++){
        var u = (x + 0.5 - cx) / rr, v = (cx - y - 0.5) / rr, rho = Math.sqrt(u * u + v * v); if (rho >= 1) continue;
        var c = Math.asin(rho), sc = Math.sin(c), cc = Math.cos(c);
        var lat = rho ? Math.asin(cc * sp + v * sc * cp / rho) : p0, dl = Math.atan2(u * sc, rho * cc * cp - v * sc * sp);
        var shade = 0.72 + 0.28 * Math.pow(cc, 0.6);                                   /* a little limb darkening, as in the photos */
        idx.push((y * N + x) * 4); grid.push(((90 - lat / D) / 180 * TH) | 0, dl / D, shade);
      }
    }
    function draw(sub){
      if (gridLat == null || (!POLE && Math.abs(sub.lat - gridLat) > 0.25)) build(sub.lat);
      var off = POLE ? sub.lon - wantAng : sub.lon;   /* pole: screen angle th shows longitude subLon + (th - sunAngle) */
      for (var k = 0, j = 0; k < idx.length; k++, j += 3){
        var row = Math.min(TH - 1, grid[j]), lon = off + grid[j + 1];
        var col = ((((lon + 180) / 360) % 1 + 1) % 1 * TW) | 0, s = (row * TW + col) * 4, d = idx[k], sh = grid[j + 2];
        px[d] = TEX[s] * sh; px[d + 1] = TEX[s + 1] * sh; px[d + 2] = TEX[s + 2] * sh; px[d + 3] = 255;
      }
      g.putImageData(img, 0, 0);
      lastLon = off; lastLat = sub.lat;
      o.onframe && o.onframe(cv.toDataURL('image/jpeg', 0.86), POLE ? { lat: 90, lon: sub.lon - wantAng - 90, sub: sub } : sub);
    }
    function pump(){
      if (busy || want == null || !TEX) return;
      var sub = subsolar(want), off = POLE ? sub.lon - wantAng : sub.lon;
      if (lastLon != null && Math.abs(((off - lastLon + 540) % 360) - 180) < 0.2 && (POLE || Math.abs(sub.lat - lastLat) < 0.05)) return;
      var wait = Math.max(0, 66 - (Date.now() - lastT)); busy = true;
      setTimeout(function(){ busy = false; lastT = Date.now(); draw(subsolar(want)); }, wait);
    }
    if (!TEX){ waiting.push(pump); if (waiting.length === 1) loadTex(0); }
    return { set: function(ms, ang){ want = ms; if (ang != null) wantAng = ang; pump(); }, subsolar: subsolar };
  }
  window.BVGlobe = { make: make, subsolar: subsolar };
})();
