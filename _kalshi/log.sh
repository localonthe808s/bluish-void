#!/bin/sh
# Log a Kalshi fill and push it, so the next run scores it.
#
#   ./_kalshi/log.sh <date> <market> <yes|no> <strike> <price¢> <contracts> [note]
#   ./_kalshi/log.sh 2026-09-05 ny yes 78- 26 100
#   ./_kalshi/log.sh today ny no 79-80 44 50 "second window"
#
# `today` is accepted in place of a date.
set -eu
[ $# -ge 6 ] || { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
d=$1; [ "$d" = today ] && d=$(date +%Y-%m-%d)
here=$(cd "$(dirname "$0")/.." && pwd)
printf '%s,%s,%s,%s,%s,%s,%s\n' "$d" "$2" "$3" "$4" "$5" "$6" "${7:-}" >> "$here/_kalshi/trades.csv"
cd "$here"
git add _kalshi/trades.csv
git commit -q -m "trade: $d $2 $3 $4 at ${5}c x$6"
git push -q
echo "logged: $d $2 $3 $4 at ${5}c x$6"
