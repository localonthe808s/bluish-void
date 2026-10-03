# Kalshi nightly review

Every night at 10:00Z (6 AM ET) a cloud Claude session (claude.ai routine "Kalshi nightly review") runs these
instructions on a fresh checkout. The numbers already learn on their own (5-minute bake, nightly refit + tune,
see `.github/workflows/kalshi-nightly.yml`). This review is the part that finds what the numbers cannot: bugs,
wrong-way confidence, a court that never fires, a study nobody reads.

At 12:00Z the worker (`reviewDigest` in `cron-worker/kalshi-cron.js`) reads `_kalshi/reviews/latest.json` from
the branch `claude/kalshi-review-<ET date>` and pages a summary to the phone.

## Hard rules

- **Never push to `main`.** All output goes to the branch `claude/kalshi-review-<today's ET date, YYYY-MM-DD>`.
  `main` deploys the live site. The owner merges a fix by hand, or not.
- Never place, cancel or simulate an order against a Kalshi account; never ask for, read or store any
  credential or token. The public market API (`api.elections.kalshi.com/trade-api/v2`, no auth) is fine.
- Never hand-edit a learned value to "help" (tuned.json, offsets, court thresholds, guardrails, MIN_GAIN,
  LIVE_GAIN, START dates). If a guardrail looks wrong, say so in a finding with the evidence; do not loosen it.
- No `git stash`. No emoji anywhere. No purple in any UI change.
- A fix must be a bug fix with a demonstrated before/after (a replay, a recomputed row, a parse), small and
  surgical. No refactors, no reformatting, no new features. index.html is ~huge with inline JS: touch it only
  for a clear bug, and parse-check every inline script after (pip install esprima; esprima.parseScript).
- Present derived numbers as derived. A computed value is never "the reading".

## What to do each night

1. **The settled day.** For each city (ny, las, aus) read yesterday's row in `kalshi_<city>.json` `history`
   (date = yesterday ET): actual vs our noon lock (`lock.pred/sd/pick`), the market pick, the bracket hit or
   miss. Note runs of the same-signed miss (3+ days one way is a finding). Lows: `kalshi_low_<city>.json`.
2. **The trail.** `https://cdn.bluishvoid.com/kalshi/trail/<key>_<date>.jsonl` (keys ny_high, las_high,
   aus_high; one JSON row per bake). Look for wrong-way confidence: `p` above 0.6 on a bracket that lost, a
   floor (`obs.own5`, `obs.six`, `obs.cli`) that moved backwards, a pick that flips back and forth more than
   twice after noon, a `decided`/`locked` that later contradicted the settlement, readings stamped on the wrong
   local date. Each of these was a real bug in September; see the comments in `kalshi_daily.py`.
3. **What learned overnight.** `git log --since=30.hours -- _kalshi/` on the checkout. Read the nightly refit
   commit's diffs to tuned.json (what the tuner changed and its `why`), kernel.json, dayahead.json,
   afternoon.json, price_study.json. A change is fine when its stated evidence holds; flag one whose `why`
   contradicts its own numbers.
4. **Courts that never fire.** In `kalshi_report.json` and each city doc: the edge court (named bets), kernel
   court, day-ahead court, twc_in. If a court has been shut for 14+ days, say so and why (n too small vs. the
   margin really negative). Do not change the court.
5. **Studies nobody reads.** `trail_study.json`, `insider_study.json`, `kalshi_dark.json` are produced but are
   (as of 2026-10-02) not consumed by the bake. Report anything in them that moved enough to matter.
6. **Health.** `python3 -m py_compile _kalshi/*.py`; `node --check _kalshi/cron-worker/kalshi-cron.js`; the
   last 24 h of runs of `kalshi-nyc.yml` and `kalshi-nightly.yml` if `gh` is available (skip if not). The
   worker's public status is `https://bluish-void-kalshi-cron.junkyjunkjunkjunkjunk.workers.dev/` (GET only).
7. **One bug, if there is one.** If steps 1-6 found a defect with a clear cause, fix it on the branch with the
   smallest change, and show the before/after in the review. Otherwise fix nothing; a quiet night is a fine
   result.

If a network source fails, say which one and carry on; never invent a value to fill the gap.

## Output (both files, then commit and push the branch)

`_kalshi/reviews/<date>.md`: plain prose for the owner. Lead with the one-line verdict, then findings, each
with the evidence (file + numbers) and what you did. Keep it short; numbers over adjectives.

`_kalshi/reviews/latest.json`:

```json
{"date": "YYYY-MM-DD", "headline": "one sentence",
 "findings": [{"title": "short", "severity": "high|medium|low|note", "evidence": "file/number",
               "fix": false}],
 "branch": "claude/kalshi-review-YYYY-MM-DD"}
```

`fix: true` only when the branch carries a code change for it. Severity `high` = the sheet is showing a wrong
number now or a court/bake is broken; it pages loudly.
