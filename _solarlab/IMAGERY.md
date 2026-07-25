# Public-domain / open-license space imagery — research for the solar system widget

Researched 2026-07-23. Goal: real mission photos in the map + popups, following the
site's established pattern (rehost stable copies on `cdn.bluishvoid.com` R2, keep
credits in code comments + visible where license requires).

## License landscape (verified)

| Source | License | Credit required | Notes |
|---|---|---|---|
| NASA (images.nasa.gov, JPL Photojournal, mission sites) | **Public domain** (US Gov work) | Requested, not required | Insignia/logo NOT PD; identifiable people = publicity rights caveat |
| STScI Hubble (hubblesite.org) | Public domain unless stated | NASA + STScI acknowledgement requested | |
| JWST (NASA-released) | Public domain | NASA/ESA/CSA/STScI credit requested | |
| ESA/Hubble + ESA/Webb (esahubble.org, esawebb.org) | CC BY 4.0 | **Required, visible** | Fine — site already carries CC-BY credits |
| ESA missions (esa.int) | CC BY-SA 3.0 IGO | **Required + ShareAlike** | ShareAlike is viral — prefer NASA equivalents where possible |
| ESO (eso.org) | CC BY 4.0 | **Required, visible** | Already used: milkyway.webp = ESO/S. Brunier panorama |
| NOAA/SWPC | Public domain | — | Already used for solar wind |

## What the lab already uses (keep)

- Planet discs: NASA/JPL Photojournal photos rehosted at `cdn.bluishvoid.com/planet-*.jpg`
  (PIA IDs documented in the site; see planet-imagery memory/notes).
- Popup hero photos: `images-assets.nasa.gov/image/PIA…/PIA…~medium.jpg` (PD, hotlinked).
- Repo astrophotos (alpha-baked webp, credits in index.html ~line 9263):
  - `milkyway.webp` — ESO/S. Brunier, CC BY 4.0
  - `andromeda.webp` — Adam Evans, CC BY 2.0
  - `orion_neb.webp` — NASA/ESA/M. Robberto HST, public domain
  - `pleiades.webp` — NASA/ESA/AURA/Caltech Palomar, public domain

## Applied to the lab now

- **M31 Andromeda** (`andromeda.webp`) at true chart position ecl lon 27.8°, lat +33.3°.
- **M45 Pleiades** (`pleiades.webp`) at ecl lon 59.9°, lat +4.1° (on the zodiac rim).
- **M42 Orion Nebula**: projects off-canvas (lat −28.7° → beyond the top edge) — unused.
- **Live Sun**: SDO AIA 171 Å latest frame (PD, courtesy NASA/SDO & AIA/EVE/HMI teams),
  hotlinked from `sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0171.jpg`, clipped
  into the sun disc with the procedural glow kept as halo + onerror fallback.

## For the widget build-out (per body / feature)

- **Sun**: SDO latest frames, several wavelengths: `latest_512_0171.jpg` (gold corona),
  `_0304` (red chromosphere), `_HMIIC` (visible photosphere). PD. NASA GSFC endpoints
  have a history of cert/outage issues (same reason the moon moved to R2) → snapshot
  via scheduled GitHub Action → `cdn.bluishvoid.com/sun/current.jpg`, like the moon.
  SOHO LASCO C2/C3 coronagraph (ESA/NASA joint — free with credit) for CME context.
- **Mercury**: MESSENGER MDIS global mosaic (PIA15162 etc.) — PD.
- **Venus**: Magellan radar composite (PIA00104, already used) or Mariner 10 reprocessed — PD.
- **Mars**: daily-ish global view — Mars Express VMC is ESA CC BY-SA (viral);
  prefer NASA MARCI weather maps (MSSS, PD) or stick with PIA00407 Viking mosaic.
- **Jupiter**: JunoCam processed images — PD (credit NASA/JPL-Caltech/SwRI/MSSS +
  citizen processor name; some processors assert rights — prefer NASA-released ones).
- **Saturn**: Cassini PIA06077 (used) + ring/moon closeups from Photojournal — PD.
- **Uranus/Neptune**: Voyager 2 (PIA18182 used / PIA01492 used); JWST 2023 ring
  portraits are stunning + PD-when-NASA-released.
- **Moons** (STRUCTURE tab expansion): Galilean moons (Galileo/Juno PD), Titan/Enceladus
  (Cassini PD), Triton (Voyager PD) — all on Photojournal.
- **Pluto/dwarf planets** (if added): New Horizons PIA19952 etc. — PD.
- **Milky Way band**: the repo's ESO/Brunier panorama could be warped along the
  projected galactic circle (segment-and-rotate like the hero uses), CC BY 4.0.
- **Comets/asteroids** (future): OSIRIS-REx Bennu (PD); Rosetta 67P is ESA CC BY-SA (viral).

## Meteor showers (researched 2026-07-24)

For a hero photo in `openShowerPopup`, which currently has none. Every URL below was
HTTP-checked or pulled from the Commons/NASA APIs on 2026-07-24.

**Coverage is uneven — this is the headline.** Photos are plentiful for the famous
showers and near-absent for the rest, so the popup needs a graceful no-image path
rather than a photo slot that goes blank 4 times a year.

| Shower | Open imagery? | Best candidate |
|---|---|---|
| Quadrantids | thin (7 files) | none strong |
| Lyrids | **yes** | *Stunning Lyrids Over Earth at Night* — NASA/Don Pettit, **PD**, 3768×2832, shot from the ISS |
| Eta Aquariids | **yes** | ESO/P. Horálek Chilean Desert (`potw2227a/b`), **CC BY 4.0**, huge; + NASA All Sky Fireball Network mosaic (PD) |
| Delta Aquariids | **almost none** | see below |
| Perseids | **abundant** | NASA/Bill Ingalls `NHQ202508030001` + `NHQ202108100009` (**PD**); `ISS-44 Perseid meteor shower` (**PD**, from orbit) |
| Draconids | **none** (0 files) | historic *Draconids 1933, F. Quénisset* (PD) is the only thing |
| Orionids | **yes** | Mike Lewinski *Orionid meteor at dawn*, CC BY 4.0, 6000×4000 |
| Leonids | **yes** | Trouvelot *The November Meteors* (1889 lithograph of the 1833 storm), **PD**, 16975×23165 |
| Geminids | **abundant** | NOIRLab *Geminids over Gemini North* / *over Kitt Peak*, CC BY 4.0 — thematically perfect (Geminids over the Gemini telescope) |
| Ursids | **none** (1 file) | — |

### Delta Aquariids — the near-term one (peaks Jul 29)

Genuinely poorly served. Commons has **one** usable image and NASA's library has zero
(`images-api.nasa.gov?q=Delta Aquariid` → 0 hits). Options, honest ones first:

1. `Under the summer stars (54671841582).jpg` — bgwashburn, **CC BY 4.0**, 4456×5996.
   Caveat: the photographer's own caption says "a Delta Aquariid **or early Perseid**",
   so it cannot be captioned as a confirmed Delta Aquariid.
   `https://upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Under_the_summer_stars_%2854671841582%29.jpg/1920px-Under_the_summer_stars_%2854671841582%29.jpg`
2. ESO/Horálek `potw2227b` — the *Eta* Aquariids, same Aquarius radiant region. Correct
   sky, wrong shower; only usable if the caption says which shower it actually shows.
3. No photo; let the radiant fan carry it.

### Parent bodies (the per-shower angle — mostly a dead end)

The popup already has a "Parent body" row, but only two of ten have real imagery:

- **3200 Phaethon** (Geminids): `PIA22185` Arecibo radar, **PD**, Arecibo/NASA/NSF; plus
  `Phaeton-trail-copy.jpg` (NASA/NRL, PD) showing its dust trail from STEREO.
- **1P/Halley** (Eta Aquariids + Orionids): the close-up nucleus is **ESA Giotto** —
  CC BY-SA, the viral licence this doc already says to avoid. Ground-based 1986 plates
  via NASA's IHW archive are the PD alternative.
- **109P/Swift-Tuttle**, **55P/Tempel-Tuttle**: 0 openly-licensed files on Commons.
- **96P/Machholz**: only CC BY-SA skymaps/orbit diagrams, no photograph.
- 2003 EH1, C/1861 G1 Thatcher, 21P, 8P: nothing usable.

Verdict: not viable as a consistent per-shower hero. Worth doing as a one-off for the
Geminids (Phaethon is a genuinely interesting "rock comet" story) but not systemwide.

### Licence notes specific to this batch

- Most amateur Commons astrophotos are **CC BY-SA**, not CC BY. ShareAlike is fine for a
  popup hero shown **as-is with visible credit** — it only bites when baked into a
  derived composite (unlike the alpha-baked hero night-sky assets, where it must stay out).
- NOIRLab / Gemini / KPNO images are CC BY 4.0 and consistently well-shot — the single
  best institutional source for shower photos after ESO.
- NASA APOD is **not** a source: the daily images are copyright the individual
  astrophotographers, not PD, despite the nasa.gov domain.
- On-pattern hotlink form (already used for planet popups, both verified 200):
  `https://images-assets.nasa.gov/image/<nasa_id>/<nasa_id>~medium.jpg`

## Serving guidance

- Prototype: hotlink NASA endpoints (PD, CORS-irrelevant for `<img>`/SVG `<image>`).
- Production: rehost stable copies on R2/cdn (existing rclone + GH Action pipeline)
  — NASA endpoints flake (SVS cert expiry precedent) and filenames change.
- Keep every non-PD credit visible or in code comments per site convention; CC BY-SA
  (ESA mission imagery) is ShareAlike — avoid baking it into derived composites.

## Moons — which have usable public photos (audited 2026-07-25)

All 23 named moons in `MOON_SYS` have a **NASA public-domain** photo in `MOON_IMG`,
and all 23 URLs return 200. They are now drawn on the map itself, not just in popups.

**Three sources were wrong** and were replaced — they were never portraits:

| moon | was | problem | now |
|---|---|---|---|
| Callisto | PIA03455 | two-panel science figure with a scale bar | **PIA03456** global view |
| Tethys | PIA07733 | flyby *coverage map* with axes, legend and title text | **PIA19636** "The Colors of Tethys I" |
| Dione | PIA12577 | flat surface mosaic strip, no disc | **PIA06163** global view |

Note PIA03456 has **no `~medium`** asset — older Photojournal items often don't;
use the collection.json manifest and fall back to `~orig`/`~small`.

**Disc coverage** — how much of each frame the moon actually fills. This matters
because these are science releases, not cutouts: a low number means mostly black sky,
which is why every image needs the measured crop in `MOON_CROP` rather than being
dropped straight into a circular clip.

| moon | disc fills | note |
|---|---|---|
| Dione | 100% | good portrait |
| Io | 99% | good portrait |
| Triton | 94% | good portrait |
| Callisto | 92% | good portrait |
| Moon | 88% | good portrait |
| Ariel | 86% | good portrait |
| Phobos | 86% | good portrait |
| Enceladus | 79% | good portrait |
| Ganymede | 79% | good portrait |
| Iapetus | 70% | good portrait |
| Europa | 67% | good portrait |
| Mimas | 61% | good portrait |
| Miranda | 56% | good portrait |
| Tethys | 50% | small in frame |
| Titan | 42% | small in frame |
| Rhea | 38% | small in frame |
| Titania | 31% | small in frame |
| Oberon | 29% | small in frame |
| Umbriel | 26% | small in frame |
| Hyperion | 19% | small in frame |
| Proteus | 17% | small in frame |
| Deimos | 16% | small in frame |
| Nereid | 4% | barely resolved — best that exists |

**Nereid is the honest floor**: Voyager 2 never resolved it, so its disc is 4% of the
frame — a bright speck. It is still the real photograph; there is no better one.
Deimos, Hyperion and Proteus are similarly small but genuinely resolved.

Regenerate the crop table with `python3 build_moon_crops.py` if any URL changes.

## Earth — the last body without a photo (added 2026-07-25)

Every other planet had a rehosted NASA portrait; Earth was still the procedural
`earthGrad` gradient. It now carries a **live full-disc photograph** from NASA's
**DSCOVR/EPIC** camera at the L1 point, which images the entire sunlit face once
a day. Public domain (NASA). Same live treatment the Sun gets from SDO and the
Moon gets from the R2 snapshot.

- Index: `https://epic.gsfc.nasa.gov/api/natural` — JSON, and **CORS-open**
  (`Access-Control-Allow-Origin: *`), so unlike SBDB/Horizons this can be
  fetched client-side rather than baked.
- Frame URL: `/archive/natural/YYYY/MM/DD/jpg/<image>.jpg`.
  **Use the jpg, not the png** — same 1080px disc at **218 KB** versus **3 MB**.
- Geometry (measured the same way as the Sun and the moons): the frame is
  square, disc centred at (0.497, 0.497), radius **0.392 of the width**, with a
  bbox solidity of 0.78 — i.e. a true disc (pi/4 = 0.785). The image is oversized
  by 1/0.392 so the limb lands exactly on the clip circle.
- EPIC lags a couple of days and the fetch can fail, so the gradient stays
  underneath as the fallback and the image only fades in on success.
- Production: snapshot to R2 on a schedule like the moon, rather than hotlinking
  GSFC — same reasoning as the Sun (`cdn.bluishvoid.com/sun/current.jpg`).
