# Push alerts — plan

Status: **not started.** This is a design doc, not a commitment.

## The short version

SMS is out. Free carrier email-to-SMS gateways are dead — T-Mobile stopped
delivering late 2024, AT&T discontinued 17 Jun 2025, Verizon degrades now and
shuts off 31 Mar 2027. Paid SMS is ~$0.008/message, which is an uncapped bill on
a site where one severe-weather outbreak fans out to every subscriber at once.

Web Push is free and unlimited, and most of the infrastructure already exists:
a Cloudflare Worker (`proxy.bluishvoid.com`), R2, a GitHub Action, and
`manifest.webmanifest` with `display: standalone` so the PWA install path works.

Two things make this harder than it looks, and both should be settled before any
code is written:

1. **iOS only delivers push to home-screen installs.** Not Safari tabs. Users
   must Share → Add to Home Screen first. Expect roughly a 10× reach penalty
   versus SMS. Android and desktop work straight from the browser.
2. **Alert logic has to move server-side.** Push fires when the page is closed,
   so the Worker must derive each condition itself. Anything computed inside
   `index.html` today has to be reimplemented. This, not the plumbing, is the
   bulk of the work — and it's what drives the priority order below.

## Priority order

Ranked by (a) does it have to reach you when the app is closed, (b) how hard is
the server-side derivation, (c) how often it fires. A daily-digest item that
fires at a predictable time is worth far less than a warning that arrives
fifteen minutes before a tornado, and an alert that fires too often gets
notifications switched off entirely — which silently kills every tier below it.

### Tier 1 — life-safety. Ship this first, alone.

NWS watches and warnings for the saved location. Tornado, Flash Flood, Severe
Thunderstorm, Hurricane/Tropical Storm, Winter Storm/Blizzard/Ice, Extreme
Heat/Cold.

- **Source:** `api.weather.gov/alerts/active?point={lat},{lon}` — already used by
  `loadWeatherAlerts`, so the shape is known and no new dependency appears.
- **Server-side effort:** low. One poll, filter by `event` and `severity`,
  dedupe on the alert `id`.
- **Why first:** highest value, lowest effort, and it exercises the whole
  pipeline (service worker → subscription → KV → cron → push) on the simplest
  possible payload. If this tier is all that ever ships, the feature is still
  worth having.

Default to `severity: Severe|Extreme` and `urgency: Immediate|Expected`. Anything
looser and the first big outbreak trains people to ignore the app.

### Tier 2 — opportunity alerts. Cheap server-side, genuinely delightful.

These need no radar maths and fire at most once a day, so they are the natural
second slice.

| Alert | Source | Effort |
|---|---|---|
| Aurora possible tonight | SWPC Kp + darkness + cloud cover | low |
| ISS visible pass | already computed from TLE-ish maths in `_fetchIssPass` | low–medium |
| Golden hour looks good tonight | the existing scoring, ported | medium |
| Meteor shower peak + clear sky | fixed calendar + cloud cover | low |

All are schedulable — an afternoon cron, not a minute-by-minute poll — so they
cost almost nothing against the free tier.

### Tier 3 — the hard, valuable one. Only after Tiers 1–2 are stable.

"Rain starts at your location in ~20 minutes," from the radar nowcast.

This is probably the single most useful everyday alert on the whole site, and
also the most expensive: `_radarNowcast` samples RainViewer pixels, applies
steering wind and a Z-R relationship, and lives entirely in `index.html`. Porting
it to a Worker is a real project, not a slice. Lightning-within-N-miles and
FloodNet street flooding sit in this tier too — FloodNet being NYC-only makes it
a poor early candidate regardless.

### Tier 4 — digests. Deliberately last.

Morning briefing, air-quality and pollen threshold crossings, wildfire smoke
overhead. Useful, but none of it needs to interrupt anyone, and every one of
these competes for the same attention budget as Tier 1.

## Architecture

```
index.html ──subscribe──► Worker /subscribe ──► KV: sub:{endpointHash}
                                                  { endpoint, keys, lat, lon,
                                                    topics[], quietHours, tz }
Cron (*/2)  ──► Worker scheduled()
                  ├─ poll NWS alerts per distinct location
                  ├─ diff against KV: sent:{subHash}:{alertId}
                  └─ Web Push (VAPID) ──► browser ──► service worker ──► notification
```

**Pieces to build**

1. **Service worker** — the only genuinely risky piece. The site has none today.
   It must handle `push` and `notificationclick`, and it must **not** cache the
   document. A badly scoped SW serves a stale `index.html` indefinitely, which is
   a permanent version of the 10-minute Pages cache lag already seen. Start with
   a push-only worker and no `fetch` handler at all.
2. **VAPID keypair** — one-time. Public key ships in the page; private key goes in
   Worker secrets, never the repo.
3. **Subscribe UI** — permission prompt, topic checkboxes per tier, quiet hours.
   Never prompt on load; prompt on an explicit tap, or the browser-level block is
   permanent and unrecoverable.
4. **Worker endpoints** — `/subscribe`, `/unsubscribe`, `/test`.
5. **Cron trigger** — 2-minute cadence for Tier 1. Free plan allows 3 triggers per
   Worker at a 1-minute minimum, which is ample.

**Free-tier headroom:** Workers give 100k requests/day. A 2-minute cron is 720
invocations/day, leaving essentially all of it for subscribe calls. Comfortable.

## Things that will bite

- **Dedupe is mandatory.** NWS re-issues and updates alerts constantly. Key on
  the alert `id` per subscription and never send the same one twice. Without
  this, one storm sends a dozen identical notifications.
- **Prune dead endpoints.** Push services return `404`/`410` when a subscription
  expires. Delete on those codes or KV fills with corpses and every send wastes
  subrequests.
- **Payload limit is ~4KB.** Send an id and let the SW fetch details if needed.
- **Group by location, not by subscriber.** Ten people in one city should cost
  one NWS poll, not ten.
- **Quiet hours need a timezone**, and this codebase already has a documented
  trap around mixing location-local ISO strings with `timeZone:` formatting.
  Store the tz with the subscription and reuse the existing helpers.
- **A test path that doesn't wait for weather.** `/test` sending a canned
  notification to one subscription, or Tier 1 is untestable for weeks at a time.

## Rollout

| Phase | Scope | Exit criteria |
|---|---|---|
| 0 | Service worker in isolation, no push | Page still updates normally; no stale-document regression |
| 1 | VAPID + subscribe + `/test` | A notification arrives on desktop and on an installed iOS PWA |
| 2 | Tier 1 NWS warnings, single location | Correct alert, exactly once, within ~2 min of issue |
| 3 | Multi-location, quiet hours, per-topic opt-in | No duplicates across a real severe-weather day |
| 4 | Tier 2 opportunity alerts | — |
| 5 | Tier 3 nowcast, if it still seems worth it | — |

Phase 0 is worth doing on its own even if the rest is never built — it's the only
step that can damage the existing site, so it should be proven before anything
depends on it.

## Open questions

- Is the iOS install requirement acceptable, or does that alone sink it?
- Alerts for the saved location only, or every location the user has added?
- Does the golden-hour scoring get duplicated in the Worker, or extracted into
  something both can share? Duplication drifts; extraction touches working code.
