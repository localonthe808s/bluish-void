"""THE MARKETS THE SHEET TRADES -- the one list every bake and study reads.

2026-09-06: three cities kept of twenty ("drop all the cities except for the 3 we have now").
2026-10-06: Austin dropped ("its not going well there"), then Las Vegas ("we're going to focus on NY HIGH and LOW").

A key here is a kalshi_daily.MARKETS config key; the lows (kalshi_lows.py) follow the same city. To re-admit a city,
add its key here, then its rows in report.py, its tab(s) in index.html's CWK_CITIES, the nightly price study's
--city list (.github/workflows/kalshi-nightly.yml) and, for the obs log, OBS_MARKETS in cron-worker/kalshi-cron.js.
"""
ACTIVE = ('ny_high',)
