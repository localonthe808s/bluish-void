/* bvFlock -- a murmuration, a peregrine and a contrail jet on ONE canvas (2026-10-04, user: "do we now have better
   abilities at doing the bird flock on blue sky moments? ... it was really buggy and struggled to load properly"; then
   "lets bring back the plane/contrail too for it to react to, it used to flee from the plane"; then "do 1 2 3": the
   real wind aloft, real contrail persistence, the flock's day; then "the falcon would come from above ... try something
   that resembles the peregrine falcon / dont let the birds go below the hero, if you want them to disappear have them
   go behind the moon that will always be on top of this hero on the right").
   The old clear-sky flock and jet (removed 08-08, c3d8cea6) were SVG moved by CSS animations: every hero rebuild or DOM
   move restarted them, boot jank started them late, the browser repainted every bird every frame, and the contrail's
   turbulence filter re-rendered per frame. Here everything is drawn from our own clock, so nothing outside can restart
   it, and the cost is a handful of strokes per frame.
   THE FLOCK is simulated, not keyframed: 3-D boids (separation / alignment / cohesion over a spatial grid, neighbour
   count capped the way starlings watch ~7), a slowly roaming roost point that keeps them one body, an orthographic
   camera so a flock turning edge-on thins to a sliver. On top of that:
     - STARTLE that spreads bird to bird (the agitation waves of real murmurations): a bird near the falcon or the jet
       is startled, its neighbours catch it a beat later, so a dark ripple runs through the flock;
     - BANKING shows: a bird turning hard presents its wings, drawn darker -- the turn waves read as dark bands;
     - FLAP AND GLIDE: each bird alternates beats and glides, startled birds beat hard.
   THE MOON (o.moon = { x, y, r }, the hero's moon disc, drawn ABOVE this canvas) is the roost: every bird that leaves
   the sky flies into it and vanishes behind it, every bird that arrives comes out from behind it. Nothing appears or
   disappears at the edges, nothing ever goes below the floor (o.floor, a share of H: the planet bars). The flock
   otherwise keeps off the disc, so it does not hide there by accident.
   THE DAY (set({ sun: { alt, eve, month } }), plan in bvFlock.dayPlan): a loose daytime flock; through the afternoon
   groups come out of the moon and it swells to the full murmuration in the last hour of sun; around sunset it streams
   back into the moon a group at a time and the last are in by the time the hero turns to night; at sunrise it bursts
   out of the moon. Starlings murmurate most in autumn and winter: the month scales the peak.
   THE PEREGRINE stoops: it enters from above, dives at the flock with its wings tucked (a teardrop), punches through,
   then pulls out, opens its long pointed wings, circles a loop or two in flap-and-glide, banked into the turn, and
   leaves off the nearer side.
   THE JET (the old _heroPlane's airliner, its exact paths) crosses every ~30-50 s on a gentle climb, aimed near the
   flock's height; its path runs well past both edges so its trail does too. The contrail follows the air at cruise
   height: none when the air is too warm, a short-lived pair of lines in dry air, a long spreading trail in
   ice-supersaturated air; it drifts with the real wind aloft. The haze is soft puffs on a quarter-resolution canvas
   scaled up (a free blur, lumpy, no seams). The flock DODGES the jet (the old 14 % dodge), birds near it scatter.
   Usage:  var f = bvFlock(canvas, { W, H, n, seed, fps, falcon, showFalcon, size, band, floor, moon, jet, wind, trail,
                                     spread, contrail, sun });
           f.set({...}); f.stats(); f.jetNow(); f.falconNow(); f.destroy();     bvFlock.dayPlan(alt, eve, month)
           bvFlock.contrail(tC, rhIce) -> { forms, life, spread, kind }
   Lab: _cloudlab/clear_sky_lab.html (the master copy -- edit there, then copy here). LIVE from 2026-10-05: the controller
   at the end of this file (window._bvFlockSync), called by _updateHeroWx, runs it over the clear-day hero. */
(function(){
  function rng(seed){ var s = seed >>> 0 || 1; return function(){ s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
  function ramp(a, a0, a1){ return a <= a0 ? 0 : a >= a1 ? 1 : (a - a0) / (a1 - a0); }
  function wrap(a){ while (a > Math.PI) a -= 6.283185; while (a < -Math.PI) a += 6.283185; return a; }

  /* the airliner from below, pointing +x, in the old _heroPlane's units (about 9.7 long) */
  var JET = [
    ['M0.9 -0.45 L-1.65 -4.25 Q-1.9 -4.62 -2.25 -4.42 L-2.62 -4.1 L-0.78 -0.42 Z', '#3b4860'],
    ['M0.9 0.45 L-1.65 4.25 Q-1.9 4.62 -2.25 4.42 L-2.62 4.1 L-0.78 0.42 Z', '#36425a'],
    ['M-3.1 -0.38 L-4.1 -1.78 Q-4.25 -1.98 -4.45 -1.86 L-4.62 -1.7 L-4.0 -0.32 Z', '#38455e'],
    ['M-3.1 0.38 L-4.1 1.78 Q-4.25 1.98 -4.45 1.86 L-4.62 1.7 L-4.0 0.32 Z', '#333f57'],
    ['M-3.35 -0.04 L-4.68 -0.72 Q-4.88 -0.8 -4.92 -0.58 L-3.92 0.06 Z', '#4d5c78'],
    ['M4.8 0 Q4.62 -0.4 3.5 -0.47 L-3.0 -0.5 L-4.55 -0.24 Q-4.85 0 -4.55 0.24 L-3.0 0.5 L3.5 0.47 Q4.62 0.4 4.8 0 Z', 'FUSE'],
    ['M4.8 0 Q4.7 -0.28 4.15 -0.4 Q4.45 -0.12 4.5 0 Q4.45 0.12 4.15 0.4 Q4.7 0.28 4.8 0 Z', '#242e44'],
    ['M0.77 -2.16 L1.53 -2.16 A0.27 0.27 0 0 1 1.53 -1.62 L0.77 -1.62 A0.27 0.27 0 0 1 0.77 -2.16 Z', '#2c374e'],
    ['M0.77 1.62 L1.53 1.62 A0.27 0.27 0 0 1 1.53 2.16 L0.77 2.16 A0.27 0.27 0 0 1 0.77 1.62 Z', '#28324a']
  ], JETP = null;
  var ENG = 1.89;   /* the nacelles' offset from the centreline: the contrails come from here */

  /* THE FLOCK'S DAY. frac = share of the peak flock in the sky; mode: 'day' | 'murmur' | 'roost' | 'emerge' | 'none'.
     alt = sun altitude (deg), eve = past solar noon, month 1-12. */
  function season(month){ return [1, 1, 0.85, 0.6, 0.4, 0.4, 0.4, 0.4, 0.75, 1, 1, 1][((month || 10) - 1) % 12]; }
  function dayPlan(alt, eve, month){
    var se = season(month), DAY = 0.3;
    if (eve){
      if (alt > 15) return { frac: DAY * se, mode: 'day', season: se };
      if (alt > 4)  return { frac: (DAY + (1 - DAY) * (1 - (alt - 4) / 11)) * se, mode: 'murmur', season: se };   /* gathering */
      if (alt > 2) return { frac: se, mode: 'murmur', season: se };                                            /* the peak */
      if (alt > -0.3) return { frac: se * (alt + 0.3) / 2.3, mode: 'roost', season: se };   /* home in groups; the last are in by -0.8, where the hero turns to night */
      return { frac: 0, mode: 'none', season: se };
    }
    if (alt < -0.8) return { frac: 0, mode: 'none', season: se };
    if (alt < 4) return { frac: DAY * se * 1.6 * ramp(alt, -0.8, 1.5), mode: 'emerge', season: se };          /* the dawn burst */
    if (alt < 12) return { frac: DAY * se * (1.6 - 0.6 * (alt - 4) / 8), mode: 'day', season: se };           /* some go off to feed */
    return { frac: DAY * se, mode: 'day', season: se };
  }
  /* THE CONTRAIL from the air at cruise height. Schmidt-Appleman, simplified for ~250 hPa: an engine trail forms only
     when the air is colder than about -40 C. It PERSISTS and spreads only where the air is supersaturated with
     respect to ice (RH over ice >= 100 %); in drier air it sublimates within seconds. The lifetimes are a display
     scale, not physics: the panel is ~10 s of flight across. */
  function contrail(tC, rhIce){
    if (tC == null || rhIce == null) return { forms: true, life: 24, spread: 1, kind: 'no data' };
    if (tC > -40) return { forms: false, life: 0, spread: 0, kind: 'none (air too warm at cruise height)' };
    /* every trail that forms spans the whole panel before it fades (user 2026-10-04: "i enjoyed the contrails that went
       across the full screen more ... they can be thinner"): the air sets how thin and how long it stays, not whether
       it reaches across. A crossing is ~10 s, so 14 s is the floor. */
    if (rhIce >= 100) return { forms: true, life: 45, spread: 1.1, kind: 'persistent, spreading' };
    if (rhIce >= 70) { var f = (rhIce - 70) / 30; return { forms: true, life: 14 + f * 20, spread: 0.5 + f * 0.5, kind: 'lingering' }; }
    return { forms: true, life: 14, spread: 0.35, kind: 'thin, fading once across' };
  }

  window.bvFlock = function(cv, o){
    o = Object.assign({ W: 1180, H: 620, n: 600, seed: 7, fps: 30, falcon: true, showFalcon: true, size: 1, band: [0.10, 0.55], floor: 0.78,
                        moon: null, jet: true, wind: 12, trail: 24, spread: 1, contrail: true, jetFirst: 5, sun: null }, o || {});
    if (!JETP && window.Path2D) JETP = JET.map(function(p){ return [new Path2D(p[0]), p[1]]; });
    var ctx = cv.getContext('2d'), R = rng(o.seed), dpr = Math.min(2, window.devicePixelRatio || 1);
    var fc = document.createElement('canvas'), fx2 = fc.getContext('2d'), FQ = 0.25;   /* the contrail haze, quarter res */
    var N = 0, MAX = 3000;
    var px = new Float32Array(MAX), py = new Float32Array(MAX), pz = new Float32Array(MAX);
    var vx = new Float32Array(MAX), vy = new Float32Array(MAX), vz = new Float32Array(MAX);
    var ph = new Float32Array(MAX), fr = new Float32Array(MAX), gt = new Float32Array(MAX), gl = new Uint8Array(MAX);
    var hd = new Float32Array(MAX), bk = new Float32Array(MAX), sk = new Float32Array(MAX), sk2 = new Float32Array(MAX);
    var role = new Uint8Array(MAX);                     /* 0 in the flock, 2 going home (into the moon) */
    var uk = new Float32Array(MAX), lt = new Float32Array(MAX);   /* the form: each bird's rank along a ribbon (0 = head) and its side offset */
    var kr = new Float32Array(MAX), ka = new Float32Array(MAX), uh = new Float32Array(MAX), ph2 = new Float32Array(MAX);   /* its fixed slot in the ball (radius, angle) and phases, worked out once */
    var ALL = [px, py, pz, vx, vy, vz, ph, fr, gt, gl, hd, bk, sk, role, uk, lt, kr, ka, uh, ph2];
    var W, H, S, ZD, RN, RS, VMIN, VMAX;
    var t = 0, dodge = 0, rome = { dil: 0, wave: 6, pulses: 0, pt: 0, side: 1 };   /* the Rome escape patterns' clocks */
    var hawk = { on: false, x: 0, y: 0, vx: 0, vy: 0, next: 9, phase: 0, w: 0.1, pt: 0, roll: 0, flap: 1, fph: 0, gt: 0, gliding: true, dir: 1, loops: 1 };   /* phase 0 stoop, 1 pull-out, 2 circling, 3 leaving */
    var plan = { frac: 1, mode: 'murmur' }, pop = { arrive: 0, leave: 0 };
    var jet = { on: false, t0: 0, dur: 10, x0: 0, y0: 0, x1: 0, y1: 0, ux: 1, uy: 0, x: 0, y: 0, next: o.jetFirst, lastS: -1 };
    var TR = { x: [], y: [], t: [], ux: 1, uy: 0 };      /* contrail samples: where the engines were, and when */
    var st = { sim: 0, draw: 0, fps: 0, frames: 0, steps: 0 };

    function dims(w, h){
      W = w; H = h; S = Math.max(0.45, Math.min(1, W / 1180));      /* phone ~ .45: distances and speeds shrink with the panel */
      ZD = 110 * S; RN = 30 * S; RS = 15 * S; VMIN = 60 * S; VMAX = 125 * S;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      cv.style.width = W + 'px'; cv.style.height = H + 'px';
      fc.width = Math.max(1, Math.round(W * FQ)); fc.height = Math.max(1, Math.round(H * FQ));
    }
    function target(){ return Math.round(o.n * plan.frac); }
    function floorY(){ return H * o.floor; }
    /* where birds go home to and come out of: the moon, or (no moon given) just past the top right corner */
    function home(){ var m = o.moon; return m ? { x: m.x, y: m.y, r: m.r } : { x: W + 60, y: -60, r: 50 }; }
    function inHome(i){ var m = home(), dx = px[i] - m.x, dy = py[i] - m.y, r = m.r * 0.92; return dx * dx + dy * dy < r * r; }   /* behind the disc = gone (0.7 let fast birds orbit it) */
    /* THE FORM (2026-10-04, from the user's own clip, youtube.com/shorts/2fu99oNUV9U: "i always liked the form they
       made here, can you copy this flow sequence and add it to their behavior? i want them to act more like
       murmurations"). What the clip shows, read off 2 s contact sheets and 0.5 s bursts:
         - a dense KNOT low over the rooftops, at the antenna mast (here: low over the planet bars);
         - a COLUMN that grows out of the knot in ~1.5 s, rooted at it, and sways like a rope into an S;
         - RIBBONS: thin curving bands in which every bird flies where the one ahead was a beat before, so the shape
           of a ribbon is the path its head has flown (crescents, S-curves, long diagonals);
         - TWO GROUPS at once, a loose one high up and the knot, trading birds along a connecting stream;
         - the stream POURS back down and condenses into the knot, then the next column or arc pulls out.
       Built as follow-the-leader on top of the boids: a LEADER flies waypoints and leaves a 10 s trail of where it was;
       a ribbon bird aims at the trail point its rank delays it to (rank x the ribbon length D), offset to its side;
       knot birds aim at the knot. The sequence moves D (how long the ribbon is) and kf (how many stay in the knot);
       birds whose side changes fly across -- the connecting streams. The boids rules still run under it (spacing,
       alignment, banking, startle), so it stays a flock, not a diagram. Phrase order and lengths follow the clip
       (a ~60 s loop): knot, high arc, pour, column, S-sway, pour, column, sway, split (mid ball + high diagonal),
       arc, pour. */
    var LD = { x: 0, y: 0, vx: 0, vy: 0, wp: [], hx: new Float32Array(300), hy: new Float32Array(300), hn: 0, hh: 0, ht: 0 };
    var KN = { x: 0, y: 0, tx: 0, ty: 0, dx: 0, dy: 0 }, SH = { cth: 1, sth: 0, ctl: 1, stl: 0, morph: 1 };
    var FORM = { swap: 0, i: 0, t: 0, D: 0.5, kf: 0.6, Dt: 0.5, kft: 0.6, name: 'ball', w: 1, wt: 1, mAmp: 0.35, mAmpT: 0.35, drift: 1, driftT: 1, sat: 0.15, motion: 'clip' };
    /* THE REPERTOIRE (user 2026-10-05: "my video should be just one of its motions"). Each motion is a phrase list; the
       flock plays them in a shuffled order, never the same twice running.
         clip   -- the user's roost clip, as read off it (knot, columns, S-sways, pours; ~60 s)
         blob   -- the Brighton clip (2026-07-13): one body morphing ball / pancake / edge-on sliver / comma / egg while it
                   travels -- the sheet turned up and the knot moving fast
         roam   -- no choreography: the boids round a wandering point, the first look the user liked
         sweep  -- Rome over the Tiber: long sheets sweeping the full width and folding back on themselves
         cordon -- Rome's escape pattern held as a shape: two groups apart on a thin string, then pouring together */
    var MOTIONS = {
      clip:   [['ball', 4], ['arc', 6], ['pour', 4], ['rise', 4], ['sway', 8], ['pour', 5], ['rise', 3], ['sway', 6], ['split', 8], ['arc', 6], ['pour', 5]],
      blob:   [['blob', 8], ['blob', 8], ['blob', 8]],
      roam:   [['free', 24]],
      sweep:  [['sweep', 7], ['fold', 5], ['sweep', 7], ['fold', 5], ['pour', 4]],
      cordon: [['split', 12], ['pour', 5], ['ball', 3]]
    }, MKEYS = ['clip', 'blob', 'roam', 'sweep', 'cordon'], SEQ = MOTIONS.clip;
    /* between motions a large share of the flock goes home into the moon and the next scene fills from it: the moon as
       the doorway between scenes (the arrivals come out of it because the count dropped below the target) */
    function nextMotion(){ var k; do { k = MKEYS[(R() * MKEYS.length) | 0]; } while (k === FORM.motion); FORM.motion = k; SEQ = MOTIONS[k]; FORM.i = 0; FORM.t = 0; startPhrase(SEQ[0][0]);
      if (o.moon && N > 30) FORM.swap = Math.round(N * (0.35 + R() * 0.15)); }
    /* the sky the form plays in: clear of the moon -- left of it when it sits at the right (desktop), below it when it
       sits centred above the readout (phone; excluding by x there left a 100 px sliver) */
    function box(){ var m = o.moon, x0 = W * 0.1, x1 = W * 0.9, y0 = o.band[0] * H;
      if (m && m.x > W * 0.7) x1 = Math.min(x1, m.x - m.r * 1.4); else if (m) y0 = Math.max(y0, m.y + m.r * 1.25);
      return { x0: x0, x1: Math.max(x0 + 100, x1), y0: y0, y1: Math.max(y0 + 60, floorY() - 45 * S) }; }
    function P(fx, fy){ var b = box(); fx = Math.max(0, Math.min(1, fx)); fy = Math.max(0, Math.min(1, fy)); return [b.x0 + (b.x1 - b.x0) * fx, b.y0 + (b.y1 - b.y0) * fy]; }
    /* the ball's ground: mid-low sky, and it drifts (user 2026-10-04, of a knot pinned over the bars: "there seems to be
       a chunk of birds that always stay at the bottom") */
    var roost = { x: 0, y: 0 };
    function roostAt(tt){
      var b = box();
      roost.x = b.x0 + (b.x1 - b.x0) * (0.5 + 0.40 * Math.sin(tt * 0.071 + 1.3) + 0.08 * Math.sin(tt * 0.23));
      roost.y = b.y0 + (b.y1 - b.y0) * (0.45 + 0.35 * Math.sin(tt * 0.113 + 0.4) + 0.1 * Math.sin(tt * 0.31 + 2)) + dodge;
    }
    function knotHome(){ return P(0.25 + 0.5 * R(), 0.45 + 0.3 * R()); }
    function startPhrase(name){
      var b = box(), sd = R() < 0.5 ? -1 : 1, kx = (KN.x - b.x0) / (b.x1 - b.x0), M = function(f){ return sd > 0 ? f : 1 - f; };
      FORM.name = name; LD.wp = []; FORM.wt = 1; FORM.mAmpT = 0.35; FORM.driftT = 1;
      if (name === 'ball'){ FORM.Dt = 0.5; FORM.kft = 1.0; var k = knotHome(); KN.tx = k[0]; KN.ty = k[1]; LD.wp = [P(kx + sd * 0.12, 0.8), P(kx - sd * 0.08, 0.88)]; }
      else if (name === 'arc'){ FORM.Dt = 2.6; FORM.kft = 0.0; LD.wp = [P(M(0.15), 0.35), P(M(0.38), 0.07), P(M(0.68), 0.03), P(M(0.9), 0.2)]; }
      else if (name === 'pour'){ FORM.Dt = 3.2; FORM.kft = 0.9; var kh = knotHome(); KN.tx = kh[0]; KN.ty = kh[1];   /* the stream pours into the ball, wherever it now is */
        LD.wp = [P(kx + sd * 0.2, 0.42), P(kx - sd * 0.12, 0.7), [KN.tx, KN.ty]]; }
      else if (name === 'rise'){ FORM.Dt = 4.2; FORM.kft = 0.35; LD.x = KN.x; LD.y = KN.y; LD.vx = sd * 20 * S; LD.vy = -130 * S; LD.wp = [P(kx + sd * 0.05, 0.4), P(kx + sd * 0.17, 0.06)]; }   /* the column out of the knot */
      else if (name === 'sway'){ FORM.Dt = 4.0; FORM.kft = 0.1; LD.wp = [P(kx - sd * 0.12, 0.12), P(kx + sd * 0.12, 0.22), P(kx - sd * 0.1, 0.05), P(kx + sd * 0.14, 0.18)]; }
      else if (name === 'blob'){ FORM.Dt = 0.4; FORM.kft = 1; FORM.mAmpT = 0.75; FORM.driftT = 2.2; var kb = P(0.15 + 0.7 * R(), 0.2 + 0.5 * R()); KN.tx = kb[0]; KN.ty = kb[1]; }   /* the Brighton body: big morphs, travelling */
      else if (name === 'free'){ FORM.wt = 0; FORM.kft = 1; }                                                                     /* no form: the boids round a wandering point */
      else if (name === 'sweep'){ FORM.Dt = 5.0; FORM.kft = 0.05; var yy = 0.15 + 0.4 * R(); LD.wp = [P(M(0.02), yy), P(M(0.5), yy - 0.08), P(M(0.98), yy + 0.05)]; }   /* the full width, long */
      else if (name === 'fold'){ FORM.Dt = 4.0; FORM.kft = 0.05; LD.wp = [P(kx + sd * 0.12, 0.2), P(kx + sd * 0.02, 0.42), P(kx - sd * 0.12, 0.25)]; }   /* a tight U: the sheet folds over itself */
      else if (name === 'split'){ FORM.Dt = 2.2; FORM.kft = 0.5;   /* Rome's CORDON: two big parts on a thin string */ var k2 = P(0.3 + 0.4 * R(), 0.55); KN.tx = k2[0]; KN.ty = k2[1]; LD.wp = [P(M(0.15), 0.32), P(M(0.5), 0.12), P(M(0.85), 0.02)]; }
    }
    function histAt(delay){
      var k = Math.min(LD.hn - 1, Math.max(0, Math.round(delay * 30))), j = (LD.hh - k + 300) % 300, j2 = (j - 1 + 300) % 300;
      return [LD.hx[j], LD.hy[j], LD.hx[j] - LD.hx[k < LD.hn - 1 ? j2 : j], LD.hy[j] - LD.hy[k < LD.hn - 1 ? j2 : j]];
    }
    function formStep(dt){
      FORM.t += dt;
      if (FORM.t > SEQ[FORM.i][1]){ if (FORM.i + 1 >= SEQ.length) nextMotion(); else { FORM.i++; FORM.t = 0; startPhrase(SEQ[FORM.i][0]); } }
      FORM.D += (FORM.Dt - FORM.D) * Math.min(1, dt * 0.9); FORM.kf += (FORM.kft - FORM.kf) * Math.min(1, dt * 0.7);
      FORM.w += (FORM.wt - FORM.w) * Math.min(1, dt * 0.6); FORM.mAmp += (FORM.mAmpT - FORM.mAmp) * Math.min(1, dt * 0.5); FORM.drift += (FORM.driftT - FORM.drift) * Math.min(1, dt * 0.5);
      /* SATELLITES: a share of the flock (12-24 %, slowly rising and falling) is off the main shape -- two or three small
         loose groups wandering on their own, and a few lone birds; as the share moves, birds peel off and rejoin
         (user: "there can be more birds beyond the main sequence, they dont have to be so dense all the time") */
      FORM.sat = 0.12 + 0.12 * (0.5 + 0.5 * Math.sin(t * 0.045 + 0.9));
      /* and the whole shape breathes between tight and loose over about a minute */
      FORM.loose = 1 + 0.4 * (0.5 + 0.5 * Math.sin(t * 0.1 + 2.2));
      if (FORM.name === 'free'){ roostAt(t); }
      KN.x += (KN.tx - KN.x) * Math.min(1, dt * 0.35); KN.y += (KN.ty - KN.y) * Math.min(1, dt * 0.35);
      /* the sheet's turn, tilt and breathing, once a step (formTarget reads them per bird) */
      var th0 = 1.25 * Math.sin(t * 0.21) + 0.55 * Math.sin(t * 0.37 + 1.7), tl0 = 0.35 * Math.sin(t * 0.29 + 0.5);
      SH.cth = Math.cos(th0); SH.sth = Math.sin(th0); SH.ctl = Math.cos(tl0); SH.stl = Math.sin(tl0); SH.morph = 1 + FORM.mAmp * Math.sin(t * 0.15 * (FORM.mAmp > 0.5 ? 2.2 : 1) + 0.8);   /* blob: bigger, faster morphs */
      /* and the ball keeps travelling: a slow drift on top of where it is headed */
      var bb = box(), dr = FORM.drift; KN.dx = (bb.x1 - bb.x0) * 0.14 * dr * Math.sin(t * 0.17 * dr + 1.1); KN.dy = (bb.y1 - bb.y0) * 0.12 * dr * Math.sin(t * 0.23 * dr + 0.3);
      /* the leader: to its waypoints with a limited turn, then a slow wander round the knot until the next phrase */
      var b = box();
      if (!LD.wp.length) LD.wp = FORM.name === 'pour' || FORM.name === 'ball' ? [[KN.x + (R() - 0.5) * 120 * S, KN.y - R() * 50 * S]] : [P(R(), R() * 0.5)];
      var w = LD.wp[0], dx = w[0] - LD.x, dy = w[1] - LD.y, d = Math.hypot(dx, dy);
      if (d < 35 * S){ LD.wp.shift(); }
      var sp = (FORM.name === 'pour' ? 165 : FORM.name === 'rise' ? 150 : 135) * S, ca = Math.atan2(LD.vy, LD.vx), ta = Math.atan2(dy, dx);
      var na = ca + Math.max(-2.4 * dt, Math.min(2.4 * dt, wrap(ta - ca)));
      LD.vx = Math.cos(na) * sp; LD.vy = Math.sin(na) * sp; LD.x += LD.vx * dt; LD.y += LD.vy * dt;
      LD.x = Math.max(b.x0 - 20, Math.min(b.x1 + 20, LD.x)); LD.y = Math.max(b.y0 - 20, Math.min(b.y1, LD.y));
      LD.ht += dt; while (LD.ht >= 1 / 30){ LD.ht -= 1 / 30; LD.hh = (LD.hh + 1) % 300; LD.hx[LD.hh] = LD.x; LD.hy[LD.hh] = LD.y + dodge; if (LD.hn < 300) LD.hn++; }
    }
    /* where bird i is aiming: its point on the ribbon, or its place in the knot; each slot breathes a little so the
       inside of the shapes keeps churning */
    /* THE MOON IS A DOORWAY, NOT A HIDE (user 2026-10-05: "avoid having the birds hangout behind the moon, use the moon
       as a place for them to start and end in as scenes change"): any place in the form that falls on or near the disc is
       moved out to its rim + margin, so the shapes play beside the moon, never behind it */
    function formTarget(i){
      var p = formTarget0(i), m = o.moon; if (!m) return p;
      var dx = p[0] - m.x, dy = p[1] - m.y, d = Math.hypot(dx, dy), R0 = m.r * 1.6;
      if (d >= R0) return p;
      if (d < 1){ dx = -1; dy = 0.4; d = Math.hypot(dx, dy); }
      return [m.x + dx / d * R0, m.y + dy / d * R0, p[2]];
    }
    function formTarget0(i){
      var a = 1 - FORM.kf, u = uk[i], br = Math.max(0, 1 - FORM.D / 1.5), L = FORM.loose;
      var wob = 0.35 * Math.sin(t * 0.6 + ph2[i]);
      if (uh[i] < FORM.sat){
        /* a satellite: lone birds (the lowest few) each on their own slow path; the rest in one of three small loose
           groups, each wandering the sky on its own incommensurate sines */
        var bx = box(), g = uh[i] < 0.03 ? -1 : ((ph2[i] * 3 / 6.2832) | 0), fa, fb;
        if (g < 0){ fa = 0.5 + 0.45 * Math.sin(t * 0.07 + ph2[i] * 5); fb = 0.4 + 0.38 * Math.sin(t * 0.05 + ph2[i] * 3);
          return [bx.x0 + (bx.x1 - bx.x0) * fa, bx.y0 + (bx.y1 - bx.y0) * fb + dodge, 0]; }
        fa = 0.5 + 0.42 * Math.sin(t * (0.05 + g * 0.017) + g * 2.1); fb = 0.38 + 0.32 * Math.sin(t * (0.067 + g * 0.011) + g * 1.3 + 0.7);
        var sr = 55 * S * L * Math.pow(kr[i], 1.6), sa = ka[i] + wob;
        return [bx.x0 + (bx.x1 - bx.x0) * fa + Math.cos(sa) * sr, bx.y0 + (bx.y1 - bx.y0) * fb + dodge + Math.sin(sa) * sr * 0.6, Math.sin(sa * 1.7) * sr * 0.5];
      }
      if (u < a){
        var q = u / a, h = histAt(q * FORM.D), hl = Math.hypot(h[2], h[3]) || 1, nx = -h[3] / hl, ny = h[2] / hl;
        var wd = ((6 + 15 * Math.sin(Math.PI * Math.min(1, q * 1.1))) * S + br * 34 * S) * L, lo = Math.sin(ph2[i] * 3) * 0.5 * br * 56 * S * L;
        return [h[0] + nx * (lt[i] + wob) * wd + h[2] / hl * lo, h[1] + ny * (lt[i] + wob) * wd + h[3] / hl * lo];
      }
      /* THE BALL IS A SHEET (STARFLAG, Rome: real flocks are thin sheets, densest at their edges). Each knot bird has a
         slot on an ellipse, crowded toward the rim (r = h^0.35), on a plane that slowly turns about the vertical and
         tilts; seen from the ground a sheet turning edge-on squeezes into a dense dark band -- BLACKENING, the commonest
         pattern in the Rome falcon films -- and opens back out as it turns away. The ellipse also breathes between
         pancake and egg. */
      /* the ball scales with how many birds are in it (sqrt of the share) and breathes with the looseness */
      var bs = Math.sqrt(Math.max(0.15, FORM.kf * (1 - FORM.sat)) * Math.max(1, N) / 350) * L;
      var an = ka[i] + wob * 0.6, pa = kr[i] * Math.cos(an) * 64 * S * SH.morph * bs, qb = kr[i] * Math.sin(an) * 30 * S / SH.morph * bs;
      return [KN.x + KN.dx + pa * SH.cth, KN.y + KN.dy + dodge + qb * SH.ctl + pa * SH.sth * SH.stl * 0.4, pa * SH.sth];
    }
    function init(i, x, y, z, ux, uy, r){
      px[i] = x; py[i] = y; pz[i] = z; vx[i] = ux; vy[i] = uy; vz[i] = (R() - 0.5) * 20 * S;
      ph[i] = R() * 6.283; fr[i] = 11 + R() * 5; gt[i] = R() * 2; gl[i] = 0; hd[i] = Math.atan2(uy, ux); bk[i] = 0; sk[i] = 0; role[i] = r || 0; uk[i] = R(); lt[i] = R() * 2 - 1; kr[i] = Math.pow(R(), 0.35); ka[i] = R() * 6.2832; uh[i] = R(); ph2[i] = R() * 6.2832;   /* kr: crowded toward the rim -- Rome flocks are densest at their edges */
    }
    function spawnBall(i){
      var a = R() * Math.PI * 2, u = R() * 2 - 1, r = Math.cbrt(R()) * 60 * S, q = Math.sqrt(1 - u * u);
      init(i, KN.x + r * q * Math.cos(a) * 1.6, KN.y - Math.abs(r * u * 0.7), r * q * Math.sin(a), (KN.x > W / 2 ? -80 : 80) * S, (R() - 0.5) * 20 * S);
    }
    function setN(n){ n = Math.max(0, Math.min(MAX, n | 0)); for (var i = N; i < n; i++) spawnBall(i); N = n; }
    function kill(i){ N--; if (i !== N) for (var a = 0; a < ALL.length; a++) ALL[a][i] = ALL[a][N]; }
    function centroid(){ var cx0 = 0, cy0 = 0, m = 0; for (var a = 0; a < N; a += 7) if (!role[a]){ cx0 += px[a]; cy0 += py[a]; m++; }
      return m ? [cx0 / m, cy0 / m] : [W / 2, H * 0.3]; }

    /* POPULATION, all through the moon. Arrivals come out from behind it in groups (big bursts at dawn); departures
       peel a group off the side of the flock nearest the moon and fly it home; at sunset that runs all through the
       roost window, a group every fraction of a second, so the flock streams in rather than vanishing at once. */
    function populate(dt){
      var tg = target(), m = plan.mode, hm = home(), c0 = 0;
      for (var i = 0; i < N; i++) if (role[i] === 0) c0++;
      var swapping = FORM.swap > 0 && (m === 'day' || m === 'murmur');
      if ((swapping || c0 > tg + (m === 'roost' ? 0 : 4)) && (pop.leave -= dt) <= 0){
        pop.leave = m === 'roost' || swapping ? 0.25 + R() * 0.3 : 0.8 + R() * 0.8;
        var lead = -1, best = 1e18;
        for (var i2 = 0; i2 < N; i2++){ if (role[i2]) continue; var dx = px[i2] - hm.x, dy = py[i2] - hm.y, d2 = dx * dx + dy * dy; if (d2 < best){ best = d2; lead = i2; } }
        var want = swapping ? Math.min(FORM.swap, 30) : Math.min(c0 - tg, 30), got = 0;
        for (var j = 0; j < N && got < want && lead >= 0; j++){ if (role[j]) continue;
          var ex = px[j] - px[lead], ey = py[j] - py[lead]; if (ex * ex + ey * ey < 3600 * S * S){ role[j] = 2; got++; } }
        if (swapping) FORM.swap = got ? Math.max(0, FORM.swap - got) : 0;
      }
      if (c0 < tg && (pop.arrive -= dt) <= 0){   /* (not else: during a swap they go in and come out at once) */
        var burst = m === 'emerge';
        pop.arrive = burst ? 0.9 + R() * 1.4 : 0.6 + R() * 1.0;
        var g = Math.min(tg - c0, burst ? 25 + (R() * 40 | 0) : 8 + (R() * 22 | 0), MAX - N);
        /* out from behind the disc, heading into the open sky (down and left of it) */
        var ang = Math.PI * (0.62 + R() * 0.3), sp = 110 * S;
        for (var k = 0; k < g; k++){
          var a = R() * 6.283, rr = Math.sqrt(R()) * hm.r * 0.45;
          init(N, hm.x + Math.cos(a) * rr, hm.y + Math.sin(a) * rr, (R() - 0.5) * 30 * S, Math.cos(ang) * sp, Math.sin(ang) * sp + 30 * S, 0); N++; }
      }
      for (var r2 = N - 1; r2 >= 0; r2--) if (role[r2] === 2 && inHome(r2)) kill(r2);
    }

    /* spatial grid: counting sort of birds into cells of the neighbour radius */
    var cellOf = new Int32Array(MAX), order = new Int32Array(MAX), start = null, fillA = null, GX, GY, GZ, X0, Y0, Z0;
    function grid(){
      X0 = -W * 0.5; Y0 = -H * 0.5; Z0 = -ZD * 2;
      GX = Math.ceil(W * 2 / RN) + 1; GY = Math.ceil(H * 2 / RN) + 1; GZ = Math.ceil(ZD * 4 / RN) + 1;
      var nc = GX * GY * GZ;
      if (!start || start.length < nc + 1){ start = new Int32Array(nc + 1); fillA = new Int32Array(nc + 1); } else start.fill(0, 0, nc + 1);
      for (var i = 0; i < N; i++){
        var cx = Math.max(0, Math.min(GX - 1, ((px[i] - X0) / RN) | 0)), cy = Math.max(0, Math.min(GY - 1, ((py[i] - Y0) / RN) | 0)),
            cz = Math.max(0, Math.min(GZ - 1, ((pz[i] - Z0) / RN) | 0)), c = cx + GX * (cy + GY * cz);
        cellOf[i] = c; start[c + 1]++;
      }
      for (var k = 0; k < nc; k++) start[k + 1] += start[k];
      fillA.set(start.subarray(0, nc));
      for (var j = 0; j < N; j++) order[fillA[cellOf[j]]++] = j;
    }

    /* the jet's path runs EXT past both edges: the trail then runs off both sides, and a wind that drifts it sideways
       brings in more trail, never a cut-off end */
    var EXT = 420;
    function launchJet(){
      var c = centroid(), dir = R() < 0.5 ? 1 : -1, sp = 120 * S + 20;
      var y0 = Math.max(0.12 * H, Math.min(0.42 * H, c[1] + (R() - 0.5) * 70 * S)), y1 = y0 - H * (0.04 + R() * 0.05);
      /* the climb is set across the panel (left y0 -> right y1 for a left-to-right flight), extended along the line */
      var k = (y1 - y0) / (W + 140) * dir, yl = (dir > 0 ? y0 : y1) - k * EXT, yr = (dir > 0 ? y1 : y0) + k * EXT;
      var xa = -70 - EXT, xb = W + 70 + EXT;
      jet.x0 = dir > 0 ? xa : xb; jet.x1 = dir > 0 ? xb : xa; jet.y0 = dir > 0 ? yl : yr; jet.y1 = dir > 0 ? yr : yl;
      var dx = jet.x1 - jet.x0, dy = jet.y1 - jet.y0, L = Math.hypot(dx, dy);
      jet.ux = dx / L; jet.uy = dy / L; jet.dur = L / sp; jet.t0 = t; jet.on = true; jet.lastS = -1;
      TR.x.length = TR.y.length = TR.t.length = 0; TR.ux = jet.ux; TR.uy = jet.uy;
    }
    /* the peregrine: from above the sky, beside the flock, diving at it */
    /* how close the segment a->b comes to the moon's centre (px), or Infinity without a moon */
    function moonGap(ax, ay, bx, by){ var m = o.moon; if (!m) return 1e9; var vx0 = bx - ax, vy0 = by - ay, l2 = vx0 * vx0 + vy0 * vy0 || 1;
      var u = Math.max(0, Math.min(1, ((m.x - ax) * vx0 + (m.y - ay) * vy0) / l2)); return Math.hypot(ax + vx0 * u - m.x, ay + vy0 * u - m.y) - m.r; }
    /* THE DIVE IS ALWAYS IN THE OPEN (user 2026-10-05: "i dont like seeing falcon dives hidden by the moon"): it only
       attacks when its line down to the flock, and on past it, clears the disc by a margin -- trying both sides and a few
       offsets -- and holds off a few seconds when none does or the flock is beside the moon */
    function launchHawk(){
      var c0 = centroid(), m = o.moon, ok = false, hx = 0, mg = 30 * S + 10;
      if (m && Math.hypot(c0[0] - m.x, c0[1] - m.y) < m.r * 2.2){ hawk.next = t + 4; return; }
      for (var tr = 0; tr < 8 && !ok; tr++){
        var side = (tr & 1) ? -1 : 1; if (R() < 0.5) side = -side;
        hx = Math.max(40, Math.min(W - 40, c0[0] + side * (140 + R() * 120) * S));
        var ex2 = c0[0] + (c0[0] - hx) * 0.4, ey2 = c0[1] + (c0[1] + 40) * 0.4;     /* and the punch-through beyond */
        ok = moonGap(hx, -40, c0[0], c0[1]) > mg && moonGap(c0[0], c0[1], ex2, ey2) > mg;
      }
      if (!ok){ hawk.next = t + 4; return; }
      hawk.x = hx; hawk.y = -40;
      var dx = c0[0] - hawk.x, dy = c0[1] - hawk.y, d = Math.hypot(dx, dy) || 1, sp = 470 * S;
      hawk.vx = dx / d * sp; hawk.vy = dy / d * sp; hawk.on = true; hawk.phase = 0; hawk.w = 0.1; hawk.pt = 0; hawk.roll = 0; hawk.flap = 1; hawk.gliding = true;
    }

    var K = 9, RN2, RS2;
    function step(dt){
      t += dt; formStep(dt); grid(); RN2 = RN * RN; var cF = centroid();
      /* DILUTION: after an attack the Rome flocks spread out (~15 s); birds keep wider spacing while it lasts */
      if (rome.dil > 0) rome.dil -= dt; var dilF = 1 + 0.7 * Math.max(0, Math.min(1, rome.dil / 5)); RS2 = RS * RS * dilF * dilF;
      /* WAVE EVENTS: dark pulses run through the flock without any attack too -- ~3 pulses 0.86 s apart, ~3.5 s in all
         (Storms et al. 2019). Kicked off at the flock's edge: a few birds there startle, the startle spreads. */
      if (N > 40 && (plan.mode === 'day' || plan.mode === 'murmur')){
        rome.wave -= dt;
        if (rome.wave <= 0 && !rome.pulses){ rome.pulses = 2 + (R() < 0.6 ? 1 : 0); rome.pt = 0; rome.side = R() < 0.5 ? -1 : 1; rome.wave = 7 + R() * 9; }
        if (rome.pulses && (rome.pt -= dt) <= 0){
          rome.pulses--; rome.pt = 0.86;
          var e = -1, ev = -1e9; for (var q0 = 0; q0 < N; q0 += 3){ if (role[q0]) continue; var sc = px[q0] * rome.side; if (sc > ev){ ev = sc; e = q0; } }
          if (e >= 0) for (var q1 = 0; q1 < N; q1++){ var ddx0 = px[q1] - px[e], ddy0 = py[q1] - py[e]; if (ddx0 * ddx0 + ddy0 * ddy0 < 900 * S * S) sk[q1] = 1; }
        }
      }
      var fl = floorY();
      /* the peregrine: every ~15-25 s while there is a flock to hunt */
      if (o.falcon && N > 20 && (plan.mode === 'day' || plan.mode === 'murmur') && !hawk.on && t > hawk.next) launchHawk();
      if (hawk.on){
        var c1 = centroid(), hs = Math.hypot(hawk.vx, hawk.vy) || 1, ca = Math.atan2(hawk.vy, hawk.vx), na = ca, ns = hs;
        hawk.pt += dt;
        if (hawk.phase === 0){
          /* the stoop: steering a little at the flock's middle, wings tucked */
          var tx = c1[0] - hawk.x, ty = c1[1] - hawk.y, td = Math.hypot(tx, ty) || 1;
          var dvx = hawk.vx + (tx / td * hs - hawk.vx) * Math.min(1, dt * 1.5), dvy = hawk.vy + (ty / td * hs - hawk.vy) * Math.min(1, dt * 1.5);
          na = Math.atan2(dvy, dvx);
          if (hawk.y > c1[1] + 25 * S || hawk.y > fl - 90 * S){
            hawk.phase = 1; hawk.pt = 0;
            /* FLASH EXPANSION: only ever after an attack, most after a fast one from above, 4-10x faster than other
               responses -- the birds round the strike burst radially outward. Then, 83 % of the time, a SPLIT, which
               the form plays as its cordon; and the flock dilutes for ~15 s. (Storms et al. 2019, Rome roosts) */
            var FR = 110 * S;
            for (var fe = 0; fe < N; fe++){ if (role[fe]) continue; var ex0 = px[fe] - hawk.x, ey0 = py[fe] - hawk.y, ed = Math.hypot(ex0, ey0) || 1;
              if (ed < FR){ var kick = (1 - ed / FR) * 260 * S; vx[fe] += ex0 / ed * kick; vy[fe] += ey0 / ed * kick; sk[fe] = 1; } }
            rome.dil = 15;
            if (R() < 0.83){ FORM.motion = 'cordon'; SEQ = MOTIONS.cordon; FORM.i = 0; FORM.t = 0; startPhrase('split'); }
          }
        } else if (hawk.phase === 1){
          /* the pull-out: swing to a climb away from where it came in, wings open, bleeding speed */
          var ga = Math.atan2(-0.66, (hawk.vx >= 0 ? 1 : -1) * 0.75);
          na = ca + Math.max(-3.2 * dt, Math.min(3.2 * dt, wrap(ga - ca))); ns = Math.max(200 * S, hs - 240 * S * dt);
          if ((hawk.vy < 0 && hawk.y < H * 0.4) || hawk.pt > 2.5){
            /* then it circles: turning toward the middle of the sky, a loop or two */
            hawk.phase = 2; hawk.pt = 0; hawk.loops = 1 + R() * 0.8;
            hawk.dir = (hawk.vx * (H * 0.35 - hawk.y) - hawk.vy * (W * 0.5 - hawk.x)) < 0 ? 1 : -1;
            /* the circle's centre: off its turning side, then pulled inside the sky and clear of the moon (the first
               version just turned in place and, starting near an edge, looped off the panel and behind the moon) */
            var CR = 170 * S / 0.95, hsp = Math.hypot(hawk.vx, hawk.vy) || 1, mn2 = o.moon;
            var ccx = hawk.x - hawk.vy / hsp * CR * hawk.dir, ccy = hawk.y + hawk.vx / hsp * CR * hawk.dir;
            var xmax = W - CR - 50; if (mn2) xmax = Math.min(xmax, mn2.x - mn2.r - CR - 10);
            var ymin = CR + 30; if (mn2 && mn2.x <= W * 0.7){ xmax = W - CR - 50; ymin = Math.max(ymin, mn2.y + mn2.r + CR + 15); }   /* phone: the moon sits centred above, so stay below it */
            hawk.cx = Math.max(CR + 50, Math.min(Math.max(CR + 50, xmax), ccx)); hawk.cy = Math.max(ymin, Math.min(Math.max(ymin, fl - CR - 50), ccy)); hawk.cr = CR;
          }
        } else if (hawk.phase === 2){
          /* circling: a steady turn, speed settling, nudged back off the edges, the floor and the very top */
          /* fly the circle round its centre: the tangent, leaning in or out by how far off the radius it is */
          var th = Math.atan2(hawk.y - hawk.cy, hawk.x - hawk.cx), dr = (Math.hypot(hawk.x - hawk.cx, hawk.y - hawk.cy) - hawk.cr) / hawk.cr;
          var want = th + hawk.dir * (Math.PI / 2 + Math.max(-0.9, Math.min(0.9, dr * 1.4)));
          na = ca + Math.max(-2.4 * dt, Math.min(2.4 * dt, wrap(want - ca))); ns = hs + (170 * S - hs) * Math.min(1, dt * 1.5);
          if (hawk.pt > hawk.loops * 6.283 / 0.95){ hawk.phase = 3; hawk.pt = 0; }
        } else {
          /* leaving: off the nearer side, climbing */
          var ea = Math.atan2(-0.5, o.moon && o.moon.x > W * 0.6 ? -1 : o.moon && o.moon.x < W * 0.4 ? 1 : (hawk.x < W / 2 ? -1 : 1));   /* leave on the side AWAY from the moon */
          na = ca + Math.max(-2 * dt, Math.min(2 * dt, wrap(ea - ca))); ns = hs + (260 * S - hs) * Math.min(1, dt);
        }
        /* and it never flies behind the moon: heading toward the disc and within two radii of it, it turns away hard */
        if (o.moon){ var mx0 = hawk.x - o.moon.x, my0 = hawk.y - o.moon.y, md0 = Math.hypot(mx0, my0) || 1;
          if (md0 < o.moon.r * 2.2 && Math.cos(na) * mx0 + Math.sin(na) * my0 < 0){
            var away = Math.atan2(my0, mx0), tg0 = away + (wrap(na - away) > 0 ? 1 : -1) * Math.PI / 2 * Math.min(1, (md0 - o.moon.r) / (o.moon.r * 1.2));
            na = ca + Math.max(-4 * dt, Math.min(4 * dt, wrap(tg0 - ca))); } }
        /* banking follows the turn rate: it rolls into its turns */
        var om = wrap(na - ca) / dt; hawk.roll += (Math.max(-0.85, Math.min(0.85, om * 0.45)) - hawk.roll) * Math.min(1, dt * 4);
        hawk.vx = Math.cos(na) * ns; hawk.vy = Math.sin(na) * ns;
        /* wings: tucked in the stoop, then beating -- steadily on the pull-out and the exit, in bursts with glides
           while it circles (flap 0..1: 1 = the full downstroke, wings straight out; 0 = the upstroke, bent at the wrist) */
        hawk.w += ((hawk.phase ? 1 : 0.08) - hawk.w) * Math.min(1, dt * 7);
        if (hawk.phase === 2){ hawk.gt -= dt; if (hawk.gt <= 0){ hawk.gliding = !hawk.gliding; hawk.gt = hawk.gliding ? 1.2 + R() * 1.2 : 0.7 + R() * 0.6; } }
        else hawk.gliding = hawk.phase === 0;
        if (hawk.gliding) hawk.flap += (1 - hawk.flap) * Math.min(1, dt * 5);
        else { hawk.fph += dt * 2 * Math.PI * 4.2; hawk.flap = 0.5 + 0.5 * Math.sin(hawk.fph); }
        hawk.x += hawk.vx * dt; hawk.y += hawk.vy * dt;
        if (hawk.y > fl){ hawk.y = fl; if (hawk.phase === 0){ hawk.phase = 1; hawk.pt = 0; } }
        if (hawk.phase >= 1 && (hawk.x < -80 || hawk.x > W + 80 || hawk.y < -80)){ hawk.on = false; hawk.next = t + 15 + R() * 10; }
      }
      /* the jet: fly, lay contrail samples, and move the roost off its line while it is near */
      var dodgeTo = 0;
      if (o.jet && !isNight && !jet.on && t > jet.next) launchJet();
      if (jet.on){
        var f = (t - jet.t0) / jet.dur;
        if (f >= 1){ jet.on = false; jet.next = t + 30 + R() * 18; }
        else {
          jet.x = jet.x0 + (jet.x1 - jet.x0) * f; jet.y = jet.y0 + (jet.y1 - jet.y0) * f;
          if (o.contrail && t - jet.lastS >= 0.06){ jet.lastS = t; TR.x.push(jet.x - jet.ux * 4.4 * JS()); TR.y.push(jet.y - jet.uy * 4.4 * JS()); TR.t.push(t); }
          var lf = (cF[0] - jet.x0) / ((jet.x1 - jet.x0) || 1), ly = jet.y0 + (jet.y1 - jet.y0) * lf;
          var ahead = (cF[0] - jet.x) * Math.sign(jet.x1 - jet.x0);
          if (ahead > -160 * S && ahead < 420 * S) dodgeTo = (cF[1] - dodge >= ly ? 1 : -1) * H * 0.14;
        }
      }
      dodge += (dodgeTo - dodge) * Math.min(1, dt * 1.1);
      while (TR.t.length && t - TR.t[0] > o.trail) { TR.x.shift(); TR.y.shift(); TR.t.shift(); }

      var b0 = o.band[0] * H - 30 * S, b1 = Math.min(o.band[1] * H + 40 * S, fl - 30 * S), HR = 70 * S, HR2 = HR * HR, JR = 150 * S;
      var dec = Math.exp(-dt / 1.3), cat = Math.min(1, dt * 7), hm = home(), mn = o.moon;
      for (var i = 0; i < N; i++){
        var x = px[i], y = py[i], z = pz[i], ro = role[i];
        var cx = Math.max(0, Math.min(GX - 1, ((x - X0) / RN) | 0)), cy = Math.max(0, Math.min(GY - 1, ((y - Y0) / RN) | 0)),
            cz = Math.max(0, Math.min(GZ - 1, ((z - Z0) / RN) | 0));
        var n = 0, ax = 0, ay = 0, az = 0, mx = 0, my = 0, mz = 0, sx = 0, sy = 0, sz = 0, sN = 0;
        search:
        for (var zz = cz - 1; zz <= cz + 1; zz++){ if (zz < 0 || zz >= GZ) continue;
          for (var yy = cy - 1; yy <= cy + 1; yy++){ if (yy < 0 || yy >= GY) continue;
            for (var xx = cx - 1; xx <= cx + 1; xx++){ if (xx < 0 || xx >= GX) continue;
              var c = xx + GX * (yy + GY * zz);
              for (var q = start[c], qe = start[c + 1]; q < qe; q++){
                var j = order[q]; if (j === i) continue;
                var ddx = px[j] - x, ddy = py[j] - y, ddz = pz[j] - z, d2 = ddx * ddx + ddy * ddy + ddz * ddz;
                if (d2 > RN2) continue;
                if (d2 < RS2 && d2 > 1e-4){ var w = 1 / d2; sx -= ddx * w; sy -= ddy * w; sz -= ddz * w; }
                if (sk[j] > sN) sN = sk[j];
                /* a bird going home flocks only with others going home: lined up with the stayers it was carried away
                   from the moon (measured: 71 'going home' birds flying off at -88 px/s); spacing still holds for all */
                if (role[j] !== ro) continue;
                ax += vx[j]; ay += vy[j]; az += vz[j]; mx += ddx; my += ddy; mz += ddz;
                if (++n >= K) break search;
              } } } }
        /* startle: fades on its own, caught from the most startled neighbour a beat later -> a travelling wave */
        var s = sk[i] * dec; if (sN * 0.92 > s) s += (sN * 0.92 - s) * cat;
        var al = 1.6 * (1 + s);                                     /* a startled flock aligns harder: the wave turns them together */
        var fx = 0, fy = 0, fz = 0;
        var coh = ro === 0 ? 0.3 + 0.4 * (1 - FORM.w) : 0.7;                              /* the form shapes the flock; cohesion only keeps it soft */
        if (n){ fx += (ax / n - vx[i]) * al + mx / n * coh; fy += (ay / n - vy[i]) * al + my / n * coh; fz += (az / n - vz[i]) * al + mz / n * coh;
          fx += sx * 900 * S; fy += sy * 900 * S; fz += sz * 900 * S; }
        if (ro === 0){
          /* the form: steer for this bird's place in it -- fast when far, easing in when close */
          var fw = FORM.w, sat = uh[i] < FORM.sat;
          if (fw > 0.01 || sat){
            var ft = formTarget(i), rx = ft[0] - x, ry = ft[1] - y, rd = Math.hypot(rx, ry) || 1, want = Math.min(VMAX * (sat ? 0.95 : 1.15), rd * 1.8 + 30 * S), gk = sat ? 1.0 : 2.0 * fw;
            fx += (rx / rd * want - vx[i]) * gk; fy += (ry / rd * want - vy[i]) * gk; fz += ((ft[2] || 0) - z) * 1.2 * (sat ? 0.5 : fw);   /* depth too: the sheet's tilt is real */
          }
          if (fw < 0.99 && !sat){
            /* 'roam': the original pull to a wandering point, growing with distance -- the flock is one body that ranges */
            var qx2 = roost.x - x, qy2 = roost.y - y, qd2 = Math.hypot(qx2, qy2, z) || 1, pl = (0.10 + Math.min(1, qd2 / (220 * S)) * 0.9) * (1 - fw);
            fx += qx2 / qd2 * pl * 55 * S; fy += qy2 / qd2 * pl * 55 * S; fz -= z / qd2 * pl * 55 * S;
          }
          if (y < b0) fy += (b0 - y) * 2.2; else if (y > b1) fy -= (y - b1) * 2.2;
          var sm = 90 * S + 20; if (x < sm) fx += (sm - x) * 3; else if (x > W - sm) fx -= (x - W + sm) * 3;
          /* keep off the moon unless going home (a bird just out of it is pushed clear) */
          if (mn){ var ox = x - mn.x, oy = y - mn.y, od = Math.hypot(ox, oy) || 1, orr = mn.r * 1.6;
            if (od < orr){ var ok = (1 - od / orr) * 750 * S; fx += ox / od * ok; fy += oy / od * ok; } }
        } else {
          /* going home: into the moon, the group funnelling as it nears the disc */
          var qx = hm.x - x, qy = hm.y - y, qd = Math.hypot(qx, qy) || 1, fun = 1 + 1.5 * (1 - Math.min(1, qd / (hm.r * 4)));
          fx += qx / qd * 140 * S * fun; fy += qy / qd * 140 * S * fun; fz -= z * 0.8;
          /* and kill the sideways swing near the disc, so they fly in rather than round it */
          if (qd < hm.r * 3){ var vr = (vx[i] * qx + vy[i] * qy) / qd; fx -= (vx[i] - vr * qx / qd) * 3; fy -= (vy[i] - vr * qy / qd) * 3; }
        }
        if (z > ZD) fz -= (z - ZD) * 3; else if (z < -ZD) fz += (-ZD - z) * 3;
        if (hawk.on){ var hx = x - hawk.x, hy = y - hawk.y, h2 = hx * hx + hy * hy;
          if (h2 < HR2 * 4){ var hdd = Math.sqrt(h2) || 1, k2 = (1 - Math.min(1, hdd / (HR * 2))) * 900 * S; fx += hx / hdd * k2; fy += hy / hdd * k2; fz += (i & 1 ? 1 : -1) * k2 * 0.4;
            if (hdd < HR * 1.2) s = 1; } }
        if (jet.on){
          /* ahead of the jet (or just under it) and near its line: scatter off the line, sideways in depth too */
          var jx = x - jet.x, jy = y - jet.y, along = jx * jet.ux + jy * jet.uy, cross = -jx * jet.uy + jy * jet.ux, ac = Math.abs(cross);
          if (along > -50 * S && along < JR * 2.2 && ac < JR){
            var kj = (1 - ac / JR) * (1 - Math.max(0, along) / (JR * 2.2)) * 1100 * S, sg = cross >= 0 ? 1 : -1;
            fx += -jet.uy * sg * kj; fy += jet.ux * sg * kj; fz += (i & 1 ? 1 : -1) * kj * 0.3;
            if (ac < JR * 0.7 && along < JR * 1.4) s = 1; } }
        /* the floor: nothing goes below the hero's sky, whatever chases it */
        if (y > fl - 20 * S) fy -= (y - fl + 20 * S) * 14;
        sk2[i] = s;
        var vmax = VMAX * (1 + 0.45 * s) * (ro ? 1.2 : 1);
        var nvx = vx[i] + fx * dt, nvy = vy[i] + fy * dt, nvz = vz[i] + fz * dt, sp = Math.hypot(nvx, nvy, nvz) || 1;
        var cl = sp > vmax ? vmax / sp : sp < VMIN ? VMIN / sp : 1;
        vx[i] = nvx * cl; vy[i] = nvy * cl * (ro ? 1 : 0.985); vz[i] = nvz * cl;   /* starlings bank more than they climb */
        if (y > fl && vy[i] > 0) vy[i] = 0;
        /* banking: how fast the heading swings (rad/s), smoothed */
        var ang = Math.atan2(vy[i], vx[i]); bk[i] = bk[i] * 0.85 + Math.abs(wrap(ang - hd[i])) / dt * 0.15; hd[i] = ang;
        /* flap and glide: alternate; a startled bird does not glide */
        gt[i] -= dt; if (gt[i] <= 0){ gl[i] = (!gl[i] && s < 0.3 && R() < 0.55) ? 1 : 0; gt[i] = gl[i] ? 0.35 + R() * 0.9 : 0.5 + R() * 1.5; }
        if (s > 0.3) gl[i] = 0;
        if (!gl[i]) ph[i] += fr[i] * (1 + 0.6 * s) * dt;
      }
      var tmp = sk; sk = sk2; sk2 = tmp; ALL[12] = sk;
      for (var p = 0; p < N; p++){ px[p] += vx[p] * dt; py[p] += vy[p] * dt; pz[p] += vz[p] * dt; if (py[p] > fl) py[p] = fl; }
      populate(dt);
      st.steps++;
    }
    function JS(){ return 3.15 * Math.max(0.6, S); }             /* jet glyph scale: the old 3 x 1.05 on desktop */

    /* THE CONTRAIL. Each sample's age sets everything: a gap behind the engines (forms ~0.2 s back), crisp twin lines
       that part slightly and fade, and haze that widens (more in moist air: o.spread), drifts with the wind aloft and
       wobbles apart (frozen per-position noise, so it breaks up rather than writhing).
       The haze is one soft puff per sample, radius jittered by position (lumps), alpha set so the overlap of
       neighbouring puffs adds up to the intended density -- no strokes, so no seams between age bins. */
    function drawTrail(){
      var n = TR.t.length; if (n < 2) return;
      /* drift: slight. A trail drifting ALONG itself is invisible in the real sky (it runs past both horizons), but on the
       panel the full 0.28 px/s per mph slid tonight's (101 mph) trail 280 px off one side in 10 s */
      var life = o.trail, wpx = o.wind * 0.06 * S, pxp = -TR.uy, pyp = TR.ux, js = JS(), sprd = o.spread;
      var c1 = Math.max(11, life * 0.8), c0 = c1 * 0.55;                          /* the crisp lines last the whole crossing, then fade */
      var gap = (120 * S + 20) * 0.06;                                             /* px between samples */
      function at(k, a, off){
        var bx = TR.x[k], by = TR.y[k], wob = Math.min(a, 14) * (0.2 * Math.sin(bx * 0.013 + 0.7) + 0.12 * Math.sin(bx * 0.041 + 2.1) + 0.04 * Math.sin(bx * 0.097 + 4.4)) * S * Math.min(1, sprd * 0.6);   /* break-up grows with the spread: dry trails stay straight */
        return [bx + wpx * a + pxp * off, by + 0.25 * a + pyp * off + wob];
      }
      fx2.setTransform(FQ, 0, 0, FQ, 0, 0); fx2.clearRect(0, 0, W, H);
      var any = false;
      for (var k = 0; k < n; k++){
        var a = t - TR.t[k], A = 0.22 * Math.min(1, sprd) * ramp(a, 0.6, 4) * (1 - ramp(a, life * 0.5, life));
        if (A <= 0.004) continue;
        var p = at(k, a, 0); if (p[0] < -80 || p[0] > W + 80) continue;
        var lump = 0.75 + 0.5 * (0.5 + 0.5 * Math.sin(TR.x[k] * 0.031 + 1.9) * Math.sin(TR.x[k] * 0.011));
        var r = (0.9 + a * 0.15 * sprd) * Math.max(0.6, S) * 1.2 * lump + 0.8;     /* slim: the planes are small */
        var m = Math.max(1, 2 * r / gap), ap = 1 - Math.pow(1 - A, 1 / m);
        fx2.fillStyle = 'rgba(255,255,255,' + ap.toFixed(4) + ')'; fx2.beginPath(); fx2.arc(p[0], p[1], r, 0, 6.2832); fx2.fill(); any = true;
      }
      if (any){ ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high'; ctx.drawImage(fc, 0, 0, W, H); }
      /* the twin lines, crisp: ONE stroke per line with an alpha gradient running along it, from the newest point
         (just behind the engines) back to where it has faded out. Alpha is a smooth function of age, and age runs
         evenly along the trail, so the trail dissolves continuously from its old end toward the plane -- no end ever
         shows (user: "i dont like seeing the end of the contrails, i want them to just fade naturally in the right
         direction"; the old per-age-bin strokes faded in ~65 px steps that read as cut ends) */
      var kA = 0; while (kA < n - 1 && t - TR.t[kA] > c1) kA++;
      if (n - 1 - kA >= 2){
        var aAt = function(kk){ var a = t - TR.t[kk]; return 0.88 * ramp(a, 0.12, 0.6) * (1 - ramp(a, c0, c1)); };
        ctx.lineCap = 'butt'; ctx.lineJoin = 'round'; ctx.lineWidth = Math.max(0.6, 0.75 * S + 0.15);
        [-1, 1].forEach(function(sd){
          var sepAt = function(kk){ return sd * (ENG * 0.55 + (t - TR.t[kk]) * 0.08) * js * 0.45; };
          var q0 = at(kA, t - TR.t[kA], sepAt(kA)), q1 = at(n - 1, t - TR.t[n - 1], sepAt(n - 1));
          if (Math.hypot(q1[0] - q0[0], q1[1] - q0[1]) < 1) return;
          var g = ctx.createLinearGradient(q0[0], q0[1], q1[0], q1[1]), M = 24;
          for (var j = 0; j <= M; j++){ var kk = Math.round(kA + (n - 1 - kA) * j / M); g.addColorStop(j / M, 'rgba(255,255,255,' + aAt(kk).toFixed(3) + ')'); }
          ctx.strokeStyle = g; ctx.beginPath();
          for (var k3 = kA; k3 < n; k3++){ var pq = at(k3, t - TR.t[k3], sepAt(k3)); if (k3 === kA) ctx.moveTo(pq[0], pq[1]); else ctx.lineTo(pq[0], pq[1]); }
          ctx.stroke();
        });
      }
    }
    function drawJet(){
      if (!jet.on || !JETP || jet.x < -80 || jet.x > W + 80) return;
      var js = JS(), g = ctx.createLinearGradient(0, -0.5, 0, 0.5);
      g.addColorStop(0, '#5d6d89'); g.addColorStop(0.45, '#39465f'); g.addColorStop(1, '#2c3750');
      ctx.save(); ctx.translate(jet.x, jet.y); ctx.rotate(Math.atan2(jet.uy, jet.ux)); ctx.scale(js, js); ctx.globalAlpha = 0.95;
      JETP.forEach(function(p){ ctx.fillStyle = p[1] === 'FUSE' ? g : p[1]; ctx.fill(p[0]); });
      ctx.strokeStyle = 'rgba(255,255,255,.5)'; ctx.lineWidth = 0.13; ctx.beginPath(); ctx.moveTo(3.9, -0.3); ctx.quadraticCurveTo(0.2, -0.52, -3.1, -0.34); ctx.stroke();
      ctx.restore();
    }
    /* THE PEREGRINE from below, pointing +x, about 21 px across with its wings out on desktop.
       Shape: w = spread (~0.1 in the stoop: wings swept tight, a teardrop; 1 after it). The beat changes the planform,
       not just the span: on the upstroke the wings bend at the wrist and sweep back, on the downstroke they reach out
       straight. Banking (roll, from its turn rate) tilts it: the wing on the side it leans toward foreshortens and turns
       toward the darker slate of the upperside. Tones, as seen from below against the sky: a dark hood and moustache,
       a paler barred body, underwings pale at the arm darkening to near-black primaries with a dark trailing edge,
       and a tail with a dark band near its tip. */
    function lerpC(a, b, f){ return 'rgb(' + Math.round(a[0] + (b[0] - a[0]) * f) + ',' + Math.round(a[1] + (b[1] - a[1]) * f) + ',' + Math.round(a[2] + (b[2] - a[2]) * f) + ')'; }
    /* dark, as a bird against the sky reads; the tones are the difference between them, not a grey bird (first pass was ~+40 lighter: a toy plane) */
    var HK = { arm: [60, 68, 86], hand: [16, 20, 30], slate: [30, 37, 52], belly: [64, 72, 90], flank: [22, 28, 40], hood: [12, 15, 23], tail: [44, 51, 67] };
    function drawHawk(){
      if (!hawk.on) return;
      var k = 0.71 * S + 0.22;   /* spread span ~3.5x a starling's (real: ~2.6x; user picked a little over life so the stoop still reads): ~21 px desktop, ~12 px phone */
      var w = hawk.w, fl = hawk.flap, span = w * (0.72 + 0.28 * fl), sweep = w > 0.5 ? (1 - fl) * 2.0 : 0, roll = hawk.roll;
      var tw = 0.7 + 0.5 * w + (hawk.phase === 1 ? 0.35 : 0);       /* the tail fans as it brakes out of the stoop */
      ctx.save(); ctx.translate(hawk.x, hawk.y); ctx.rotate(Math.atan2(hawk.vy, hawk.vx)); ctx.scale(k, k);
      /* the wings, under the body */
      [-1, 1].forEach(function(sd){
        var lean = Math.max(0, sd * roll), fs = 1 - 0.55 * lean;                 /* the far, tilted wing */
        var tipx = -3.4 - 2.6 * (1 - span) - sweep, tipy = sd * (1.5 + 9.8 * span) * fs;
        var wx = 0.4 - sweep * 0.45, wy = sd * (1.2 + 6.2 * span) * fs;          /* the wrist */
        var g = ctx.createLinearGradient(1.2, sd * 0.9, tipx, tipy);
        g.addColorStop(0, lerpC(HK.arm, HK.slate, Math.min(1, lean * 1.2))); g.addColorStop(0.5, lerpC([42, 49, 65], HK.slate, lean)); g.addColorStop(1, lerpC(HK.hand, HK.hand, 0));
        ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(2.3, sd * 0.85);
        ctx.quadraticCurveTo(1.6 - 0.8 * (1 - span) - sweep * 0.5, sd * (1.2 + 7.6 * span) * fs, tipx, tipy);   /* one smooth leading edge to the point (a kinked wrist read as an aircraft) */
        ctx.bezierCurveTo(-3.0 - 0.6 * (1 - span) - sweep * 0.6, sd * (1.2 + 6.4 * span) * fs, -2.6, sd * (0.9 + 2.4 * span) * fs, -1.5, sd * 0.7);
        ctx.closePath(); ctx.fill();
        if (w > 0.4){
          /* the dark trailing edge, and a faint covert line across the underwing */
          ctx.strokeStyle = 'rgba(14,18,28,.75)'; ctx.lineWidth = 0.5; ctx.beginPath(); ctx.moveTo(tipx, tipy);
          ctx.bezierCurveTo(-3.0 - 0.6 * (1 - span) - sweep * 0.6, sd * (1.2 + 6.4 * span) * fs, -2.6, sd * (0.9 + 2.4 * span) * fs, -1.5, sd * 0.7); ctx.stroke();
          ctx.strokeStyle = 'rgba(20,25,38,.32)'; ctx.lineWidth = 0.35; ctx.beginPath(); ctx.moveTo(1.0, sd * 1.0);
          ctx.quadraticCurveTo(0.2 - sweep * 0.3, wy * 0.7, wx - 0.9, wy * 0.92); ctx.stroke();
        }
      });
      /* the tail: paler, with a dark band near the tip */
      ctx.fillStyle = lerpC(HK.tail, HK.slate, Math.abs(roll) * 0.5); ctx.beginPath();
      ctx.moveTo(-3.0, -0.6); ctx.lineTo(-7.0, -0.85 * tw); ctx.quadraticCurveTo(-7.5, 0, -7.0, 0.85 * tw); ctx.lineTo(-3.0, 0.6); ctx.closePath(); ctx.fill();
      ctx.strokeStyle = 'rgba(16,20,30,.8)'; ctx.lineWidth = 0.5; ctx.beginPath(); ctx.moveTo(-6.45, -0.78 * tw); ctx.lineTo(-6.45, 0.78 * tw); ctx.stroke();
      /* the body: pale down the middle, dark at the flanks (the roll shifts the light to one side) */
      var gb = ctx.createLinearGradient(0, -1.05, 0, 1.05), mid = 0.5 + roll * 0.25;
      gb.addColorStop(0, lerpC(HK.flank, HK.flank, 0)); gb.addColorStop(Math.max(0.15, Math.min(0.85, mid)), lerpC(HK.belly, HK.belly, 0)); gb.addColorStop(1, lerpC(HK.flank, HK.flank, 0));
      ctx.fillStyle = gb; ctx.beginPath();
      ctx.moveTo(5.4, 0); ctx.quadraticCurveTo(5.1, -0.95, 3.6, -1.05); ctx.quadraticCurveTo(0, -1.15, -3.3, -0.6);
      ctx.lineTo(-3.3, 0.6); ctx.quadraticCurveTo(0, 1.15, 3.6, 1.05); ctx.quadraticCurveTo(5.1, 0.95, 5.4, 0); ctx.fill();
      /* the hood and moustache */
      ctx.fillStyle = lerpC(HK.hood, HK.hood, 0); ctx.beginPath(); ctx.ellipse(4.25, 0, 1.25, 0.98, 0, 0, 6.2832); ctx.fill();
      ctx.beginPath(); ctx.moveTo(3.6, -0.75); ctx.quadraticCurveTo(3.0, -0.95, 2.7, -0.55); ctx.lineTo(3.4, -0.4); ctx.closePath();
      ctx.moveTo(3.6, 0.75); ctx.quadraticCurveTo(3.0, 0.95, 2.7, 0.55); ctx.lineTo(3.4, 0.4); ctx.closePath(); ctx.fill();
      ctx.restore();
    }

    /* each bird: a short wing stroke across its heading, folding and opening with the beat (held open in a glide);
       three depth buckets, nearer = darker and wider; a banking or startled bird shows more wing and goes one darker. */
    var INK = [[14, 22, 44, 0.42], [14, 22, 44, 0.66], [10, 16, 34, 0.9], [6, 10, 24, 1]];
    var bucket = new Uint8Array(MAX);
    function draw(){
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
      drawTrail(); drawJet();
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      var L0 = 2.1 * S * o.size + 0.8, z3 = ZD / 3;
      for (var i = 0; i < N; i++){ var z = pz[i], b = z < -z3 ? 0 : z < z3 ? 1 : 2; if (bk[i] > 2.4 || sk[i] > 0.4) b++; bucket[i] = b; }
      for (var b2 = 0; b2 < 4; b2++){
        var c = INK[b2]; ctx.strokeStyle = 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + c[3] + ')';
        ctx.lineWidth = (0.85 + Math.min(2, b2) * 0.25) * Math.max(0.8, S * o.size + 0.25);
        ctx.beginPath();
        for (var i2 = 0; i2 < N; i2++){
          if (bucket[i2] !== b2) continue;
          var k = 1 + pz[i2] / ZD * 0.3, x = px[i2], y = py[i2];
          var sp = Math.hypot(vx[i2], vy[i2]) || 1, dx = vx[i2] / sp, dy = vy[i2] / sp;
          var w = gl[i2] ? 0.92 : 0.3 + 0.7 * Math.abs(Math.sin(ph[i2]));
          w *= 1 + Math.min(0.5, bk[i2] * 0.08);
          var L = L0 * k * w, back = L * (gl[i2] ? 0.25 : 0.45);
          var lx = x - dy * L - dx * back, ly = y + dx * L - dy * back, rx2 = x + dy * L - dx * back, ry2 = y - dx * L - dy * back;
          ctx.moveTo(lx, ly); ctx.lineTo(x, y); ctx.lineTo(rx2, ry2);
        }
        ctx.stroke();
      }
      if (o.falcon && o.showFalcon) drawHawk();
    }

    /* the clock: fixed 1/60 s steps from real elapsed time, capped so a stalled page SLOWS the scene rather than
       teleporting it; frames above the fps cap are skipped; paused off screen and in hidden tabs */
    var raf = 0, last = 0, acc = 0, lastDraw = 0, visible = true, alive = true, shown = false, fpsT = 0, fpsN = 0;
    function frame(now){
      raf = 0; if (!alive) return;
      if (!visible || document.hidden){ last = 0; return; }
      if (!last) last = now;
      var minGap = 1000 / o.fps - 1.5;
      if (now - lastDraw < minGap){ raf = requestAnimationFrame(frame); return; }
      var dt = Math.min(0.1, (now - last) / 1000); last = now; lastDraw = now; acc += dt;
      var t0 = performance.now(), ns = 0;
      while (acc >= 1 / 60 && ns < 6){ step(1 / 60); acc -= 1 / 60; ns++; }
      var t1 = performance.now(); draw(); var t2 = performance.now();
      st.sim = st.sim * 0.9 + (t1 - t0) * 0.1; st.draw = st.draw * 0.9 + (t2 - t1) * 0.1; st.frames++;
      fpsN++; if (now - fpsT > 1000){ st.fps = fpsN * 1000 / (now - fpsT || 1000); fpsN = 0; fpsT = now; }
      if (!shown){ shown = true; cv.style.opacity = '1'; }
      raf = requestAnimationFrame(frame);
    }
    function kick(){ if (!raf && alive) raf = requestAnimationFrame(frame); }
    var io = ('IntersectionObserver' in window) ? new IntersectionObserver(function(es){ visible = es[es.length - 1].isIntersecting; if (visible) kick(); }) : null;
    if (io) io.observe(cv);
    function onVis(){ if (!document.hidden) kick(); }
    document.addEventListener('visibilitychange', onVis);

    /* night = the clear-night hero (the galaxy view): none of this shows there -- the flock's plan already empties the
       sky by then, and the jet is grounded from the same line (-0.83, where the site's is_day flips) */
    var isNight = false;
    function applySun(sun){ if (!sun) return; plan = dayPlan(sun.alt, sun.eve, sun.month); isNight = sun.alt < -0.83; if (isNight && jet.on){ jet.on = false; TR.x.length = TR.y.length = TR.t.length = 0; } }
    dims(o.W, o.H); applySun(o.sun);
    (function(){ var k = knotHome(); KN.x = KN.tx = k[0]; KN.y = KN.ty = k[1]; LD.x = KN.x; LD.y = KN.y - 40 * S; LD.vx = 100 * S; for (var h = 0; h < 300; h++){ LD.hx[h] = LD.x; LD.hy[h] = LD.y; } LD.hn = 300; FORM.motion = ''; nextMotion(); })();   /* the first motion is a random one too */
    /* the sky opens already in its state: the flock that should be up is up and formed (a roosting or dawn sky starts
       with what is left or nothing, and plays out from there) */
    setN(plan.mode === 'emerge' ? 0 : target());
    var jetWas = o.jet; o.jet = false;
    for (var w0 = 0; w0 < 150; w0++) step(1 / 60);
    o.jet = jetWas; jet.next = t + o.jetFirst;
    cv.style.opacity = '0'; cv.style.transition = 'opacity .8s ease';
    kick();

    return {
      set: function(p){
        if (p.W != null || p.H != null){ var ow = W, oh = H; dims(p.W || W, p.H || H);
          for (var i = 0; i < N; i++){ px[i] *= W / ow; py[i] *= H / oh; } }
        if (p.sun) applySun(p.sun);
        ['fps', 'falcon', 'showFalcon', 'size', 'band', 'floor', 'moon', 'jet', 'wind', 'trail', 'spread', 'contrail', 'n'].forEach(function(k){ if (p[k] !== undefined) o[k] = p[k]; });
        if (!o.sun && p.n != null) setN(o.n);
        if (!o.jet && jet.on){ jet.on = false; jet.next = t + 5; }
        if (!o.contrail){ TR.x.length = TR.y.length = TR.t.length = 0; }
        kick();
      },
      /* "jet now" starts it just outside the panel, not EXT out */
      /* "jet now" flies the whole path, the off-screen run-in included, so the trail already reaches past the edge */
      jetNow: function(){ if (!jet.on && !isNight) launchJet(); kick(); },
      dump: function(){ var hm = home(), out = []; for (var i = 0; i < N; i++) out.push([role[i], Math.round(px[i] - hm.x), Math.round(py[i] - hm.y), Math.round(vx[i]), Math.round(vy[i])]); return { r: hm.r, b: out }; },   /* lab debugging */
      falconNow: function(){ if (!hawk.on && N > 0) launchHawk(); kick(); },
      /* the lab's motion buttons: play this motion now, from its first phrase */
      playMotion: function(k){ if (MOTIONS[k]){ FORM.motion = k; SEQ = MOTIONS[k]; FORM.i = 0; FORM.t = 0; startPhrase(SEQ[0][0]); } kick(); },
      form: function(){ return { motion: FORM.motion, sat: FORM.sat, loose: FORM.loose, phrase: FORM.name, i: FORM.i, D: FORM.D, kf: FORM.kf, knot: [KN.x, KN.y], leader: [LD.x, LD.y] }; },
      stats: function(){ var hot = 0, gh = 0, my = 0; for (var i = 0; i < N; i++){ if (sk[i] > 0.4) hot++; if (role[i]) gh++; if (py[i] > my) my = py[i]; }
        return { n: N, target: target(), mode: plan.mode, home: gh, fps: st.fps, sim: st.sim, draw: st.draw, steps: st.steps,
                 falcon: hawk.on ? ['stoop', 'pull-out', 'circling', 'leaving'][hawk.phase] : '', hawkRoll: hawk.roll, hawkX: hawk.x, hawkY: hawk.y, jet: jet.on, trail: TR.t.length, startled: hot,
                 jetX: jet.x, jetY: jet.y, dodge: dodge, maxY: my, floor: floorY() }; },
      destroy: function(){ alive = false; if (raf) cancelAnimationFrame(raf); if (io) io.disconnect(); document.removeEventListener('visibilitychange', onVis); }
    };
  };
  window.bvFlock.dayPlan = dayPlan;
  window.bvFlock.contrail = contrail;
})();

/* THE CLEAR-DAY HERO'S FLOCK ON THE SITE (2026-10-05, user: "lets push the clear day flock live").
   _updateHeroWx calls window._bvFlockSync(state, #hero-wx) at its end, every time it runs. The flock does NOT live inside
   #hero-wx: that box's SVG is rebuilt in place, which is what restarted the old CSS flock (c3d8cea6 and the July saga).
   It gets its own canvas, #hero-flock, placed in the sky bar right after #hero-wx -- over the sky art, under the moon
   (.hero-moon z 3), the readout and the bars (positioned later in the page) -- created when the hero turns clear-day,
   destroyed for every other state (clear night shows none of this). In between, a sync only re-reads the geometry.
   Reads from the page: the panel box (sky-bar width x #hero-wx height), the floor (top of #today-tl-planet-tracks), the
   moon (the measured .hero-moon disc: the birds' roost; desktop it sits at the right, phone above the readout), and the
   sun (_sunAltNow at LOCATION, the same altitude the sky colour uses; other days a midday pose).
   Off: lite mode (BV_LITE), prefers-reduced-motion, and -- the watchdog -- a machine where the flock costs more than
   9 ms a frame for 8 s running (then off for the session). Waits for the loading curtain to lift. Phone: fewer birds and
   no jet (the old rule). The air at cruise height for the contrails: Open-Meteo ECMWF 250 hPa (CORS open), hourly. */
(function(){
  var C = { f: null, cv: null, wait: 0, bad: 0, slow: false, airKey: '', airT: 0, tick: 0, last: null };
  function off(){ if (C.f){ try { C.f.destroy(); } catch(e){} C.f = null; } if (C.cv && C.cv.parentNode) C.cv.parentNode.removeChild(C.cv); C.cv = null;
    if (C.tick){ clearInterval(C.tick); C.tick = 0; } }
  /* the sun's altitude at lat/lon now -- OWN COPY: the site's _sunAltNow lives inside the wx-icons script's IIFE and is
     not reachable from here (found live 10-05: every call threw, the flock sat at its midday fallback). Same low-
     precision formula, plus the equation of time (_sunAltNow leaves it out: sunset ~11 min late in October). */
  function sunAltAt(lat, lon){
    var d = new Date(), rad = Math.PI / 180, n = Math.floor((d - new Date(Date.UTC(d.getUTCFullYear(), 0, 0))) / 864e5), B = rad * 360 / 365 * (n - 81);
    var eot = 9.87 * Math.sin(2 * B) - 7.53 * Math.cos(B) - 1.5 * Math.sin(B);
    var decl = -23.44 * Math.cos(rad * (360 / 365) * (n + 10)), solT = d.getUTCHours() + d.getUTCMinutes() / 60 + d.getUTCSeconds() / 3600 + lon / 15 + eot / 60, ha = (solT - 12) * 15;
    var s = Math.sin(rad * lat) * Math.sin(rad * decl) + Math.cos(rad * lat) * Math.cos(rad * decl) * Math.cos(rad * ha);
    return Math.asin(Math.max(-1, Math.min(1, s))) / rad;
  }
  function reduced(){ try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch(e){ return false; } }
  function phone(){ try { return window.matchMedia('(max-width: 768px)').matches; } catch(e){ return false; } }
  function geom(sb, hw){
    var sr = sb.getBoundingClientRect(), W = Math.round(sb.clientWidth || sr.width), H = Math.round(hw.offsetHeight || parseInt(hw.style.height, 10) || 0);
    var fl = 0.78, pt = document.getElementById('today-tl-planet-tracks');
    if (pt){ var pr = pt.getBoundingClientRect(); if (pr.height > 0 && H > 0){ var f = (pr.top - sr.top - 10) / H; if (f > 0.3 && f < 0.98) fl = f; } }
    var moon = null, me = document.querySelector('#panel-hero-row .hero-moon canvas, #panel-hero-row .hero-moon .moon-img') || document.querySelector('#panel-hero-row .hero-moon');
    if (me){ var mr = me.getBoundingClientRect(); if (mr.width > 10 && mr.height > 10) moon = { x: (mr.left + mr.right) / 2 - sr.left, y: (mr.top + mr.bottom) / 2 - sr.top, r: Math.min(mr.width, mr.height) / 2 }; }
    /* the top: below the summary (#conditions-briefing) -- the panel reaches the card top, under the date bar and the
       briefing text, and the flock flew through the words */
    var top = 0.08, bf = sb.querySelector('#conditions-briefing');
    if (bf){ var br = bf.getBoundingClientRect(); if (br.height > 0 && H > 0){ var tf = (br.bottom - sr.top + 16) / H; if (tf > 0 && tf < fl - 0.25) top = tf; } }
    return { W: W, H: H, floor: fl, moon: moon, band: [top, Math.max(top + 0.2, fl - 0.12)] };
  }
  /* what to hand set(): the size only when it changed (setting it resizes the canvas), the rest always */
  function box(g){ var p = { floor: g.floor, moon: g.moon, band: g.band, sun: sun() }; if (g.W !== C.gw || g.H !== C.gh){ p.W = g.W; p.H = g.H; C.gw = g.W; C.gh = g.H; } return p; }
  function sun(){
    var today = (window._tlDayOffset || 0) === 0, alt = 45, d = new Date();
    try { if (today && window.LOCATION) alt = sunAltAt(LOCATION.lat, LOCATION.lon); } catch(e){}
    try { if (window.locNowNaive) d = window.locNowNaive(); } catch(e){}
    return { alt: alt, eve: today ? d.getHours() >= 12 : false, month: d.getMonth() + 1 };
  }
  function air(){
    var L = window.LOCATION; if (!L || !C.f) return;
    var key = L.lat.toFixed(2) + ',' + L.lon.toFixed(2), now = Date.now();
    if (key === C.airKey && now - C.airT < 3600e3) return;
    C.airKey = key; C.airT = now;
    fetch('https://api.open-meteo.com/v1/forecast?latitude=' + L.lat + '&longitude=' + L.lon + '&models=ecmwf_ifs025&wind_speed_unit=mph&timezone=auto&forecast_days=1'
        + '&hourly=temperature_250hPa,relative_humidity_250hPa,wind_speed_250hPa,wind_direction_250hPa')
      .then(function(r){ return r.json(); }).then(function(j){
        if (!C.f || !j || !j.hourly) return;
        var h = j.hourly, hr = 12; try { hr = (window.locNowNaive ? window.locNowNaive() : new Date()).getHours(); } catch(e){}
        var i = Math.min(h.time.length - 1, hr), tC = h.temperature_250hPa[i], rh = h.relative_humidity_250hPa[i], sp = h.wind_speed_250hPa[i], dir = h.wind_direction_250hPa[i];
        if (tC == null || rh == null) return;
        var c = bvFlock.contrail(tC, rh);    /* ECMWF's RH is over ICE at these temperatures -- what persistence needs */
        C.f.set({ contrail: c.forms, trail: c.life || 1, spread: c.spread, wind: sp != null && dir != null ? -sp * Math.sin(dir * Math.PI / 180) : 0 });
      }).catch(function(){ C.airT = 0; });
  }
  window._bvFlockSync = function(st, hw){
    try {
      var sb = hw && hw.parentNode && hw.parentNode.classList && hw.parentNode.classList.contains('today-tl-sky-bar') ? hw.parentNode : null;
      if (st !== 'clear-day' || !sb || window.BV_LITE || C.slow || reduced() || typeof window.bvFlock !== 'function'){ off(); return; }
      if (document.getElementById('site-loading-screen')){
        if (!C.wait) C.wait = setTimeout(function(){ C.wait = 0; var h = document.getElementById('hero-wx'); window._bvFlockSync(C.last, h); }, 400);
        C.last = st; return;
      }
      C.last = st;
      if (!C.cv){ C.cv = document.createElement('canvas'); C.cv.id = 'hero-flock'; C.cv.style.cssText = 'position:absolute;left:0;top:0;z-index:0;pointer-events:none;'; }
      if (C.cv.parentNode !== sb || C.cv.previousSibling !== hw) sb.insertBefore(C.cv, hw.nextSibling);
      var g = geom(sb, hw); if (g.W < 40 || g.H < 60) return;
      if (!C.f){
        var ph = phone();
        C.gw = g.W; C.gh = g.H;
        C.f = bvFlock(C.cv, { W: g.W, H: g.H, floor: g.floor, moon: g.moon, band: g.band, sun: sun(), n: ph ? 380 : 650, jet: !ph, seed: (Date.now() / 864e5) | 0 });
        air();
        /* the sun moves, the moon and the panel settle: re-read every 20 s; the watchdog every 2 s */
        var n = 0;
        C.tick = setInterval(function(){
          if (!C.f) return;
          if (!document.hidden){
            var s = C.f.stats();
            if (s.fps > 5){ if (s.sim + s.draw > 9) C.bad++; else C.bad = Math.max(0, C.bad - 1); }
            if (C.bad >= 4){ C.slow = true; off(); return; }
          }
          if (++n % 10 === 0){ var h2 = document.getElementById('hero-wx'); if (h2 && h2.parentNode){ var g2 = geom(h2.parentNode, h2); C.f.set(box(g2)); } air(); }
        }, 2000);
      } else {
        C.f.set(box(g));
      }
    } catch(e){}
  };
  window.addEventListener('resize', function(){ var h = document.getElementById('hero-wx'); if (C.f && h) window._bvFlockSync(C.last, h); });
  /* for checking from the console: the running flock (stats(), form()) or null */
  window._bvFlock = function(){ return C.f; };
})();
