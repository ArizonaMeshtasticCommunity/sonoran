# Changelog

Every release of Sonoran, newest first.
The GitHub Releases page is the source of this file.
Do not edit it by hand. Run `python tools/release.py changelog`.
See `docs/RELEASING.md`.

## v2026.09.26 — 2026-09-26

16 pull requests merged, 4 issues closed.

#### New features

- RF tab — APRS in words, icons for APRS and aircraft, and a decoded + raw table (#228) by @logans-stuff
- One preset for the whole site, and a menu worth reading (#177) (#235)
- A settings page, and the units everything else will read (Phase A) (#241)
- The rest of the UX brief — chat, nodes list, streaks, planner, settings (#243)
- Say when the preset does not apply to the page in view (#245)

#### Fixes

- The vendored-pin monitor was green and blind (#227)
- APRS icons were invisible on the RF map (#229) by @logans-stuff
- The gaps page opens on the preset this mesh runs (#177) (#231)
- A quieter gaps page, in the order it should read (#62) (#234)
- Drop the nav hint, and filter the four pages that were missing it (#236)
- Auto-ack only where a digit cannot be a person, and Phase B copy (#238)
- Graph panning (#233), neighbor names (#240), config padding, sliding preset switch (#242) — done: #233, #240

#### Documentation

- A worked plan for the UX overhaul brief (#237)

#### Maintenance

- Verify the #201 fix on real firmware with a whole-config diff (#226)

#### Other

- The mesh graph's node search shows what it found (#223) (#224) — done: #223
- Lines that last in the still mode, and a toggle that keeps them (#222) (#225) — done: #222

#### Issues

- Done: #223 Mesh graph find a node does nothing (reported by @returnzork)
- Done: #222 Live map: Live should keep lines 30 s+, Motion should be the quick curved lines (reported by @logans-stuff)
- Done: #233 Node graph scrolling issue (reported by @returnzork)
- Done: #240 Neighbor Info packet should convert id to nodename (reported by @returnzork)
- Worked on: #177 All of Sonoran's pages should default to MediumFast first
- Worked on: #62 Coverage gaps: the page is too much, and hard to act on

#### Thank you

- Reported: @returnzork, @logans-stuff
- Code: @logans-stuff
