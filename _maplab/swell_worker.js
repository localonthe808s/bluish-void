/* THE SWELL FIELD OFF THE MAIN THREAD (perf 2026-11-17). swell_core.js is pure arithmetic over typed arrays, and on a phone its
   solve held the WATER switch for over a second. This worker loads the same file and runs bvSwellField for the page (SWL.build in
   index.html): the page posts the solver's inputs with the grid's corners instead of its lonAt / latAt functions, which are rebuilt
   here with the page's own formulas; the field comes back with its typed arrays transferred, not copied. */
self.window = self;
importScripts('swell_core.js?v=6');
onmessage = function(e){
  var d = e.data, o = d.o;
  try {
    var g = o.geo, RW = o.RW, RH = o.RH, R = 6378137;
    var yOf = function(lat){ return R * Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)); };
    var yN = yOf(g.n), yS = yOf(g.s);
    o.lonAt = function(x){ return g.w + (g.e - g.w) * x / RW; };
    o.latAt = function(y){ var Y = yN + (yS - yN) * y / RH; return (2 * Math.atan(Math.exp(Y / R)) - Math.PI / 2) * 180 / Math.PI; };
    if (o.D && !o.D.solved) o.D.solved = {};
    var F = self.bvSwellField(o);
    if (!F){ postMessage({ id: d.id, F: null }); return; }
    /* cloned, not transferred: some of the field's arrays are views on one buffer (transferring it twice detached it, 2026-11-17),
       and a clone of ~5 MB is a few milliseconds against a solve of over a second */
    postMessage({ id: d.id, F: F });
  } catch (x){ postMessage({ id: d.id, err: String(x) }); }
};
