# Changelog

Every release of Sonoran, newest first.
The GitHub Releases page is the source of this file.
Do not edit it by hand. Run `python tools/release.py changelog`.
See `docs/RELEASING.md`.

## v2026.09.30 — 2026-09-30

1 pull request merged.

#### Fixes

- Coverage runs fit their container; rounded routers can be sites (marked approximate) (#318) by @logans-stuff
  - The coverage map can include routers and repeating nodes that share only an approximate position (such as around Wickenburg) where a deployment allows it, and marks them as approximate.
  - The list of rounded positions on the coverage page shows only the preset you are viewing.
  - Coverage runs need less memory, so they stop failing on small servers.

#### Issues

- Worked on: #315 Wickenburg on the coverage map

#### Thank you

- Code: @logans-stuff

**Full changes:** https://github.com/ArizonaMeshtasticCommunity/sonoran/compare/v2026.09.29...v2026.09.30

## v2026.09.29 — 2026-09-29

1 pull request merged.

#### New features

- Per-caller API request budget; node page reads sightings from covering indexes (part of #304) (#316) by @logans-stuff
  - Node pages open without waiting for "Links and routes". Once this release's database update has run, the links panel itself loads in under a second instead of 5 to 30.
  - An optional per-caller limit on API requests, to slow down bulk scraping. It is off unless a deployment turns it on, and normal use is far below it.

#### Issues

- Worked on: #304 Node page: health panel and Links wait up to 29 s on /routes (packet_seen joins), measured on production

#### Thank you

- Code: @logans-stuff

**Full changes:** https://github.com/ArizonaMeshtasticCommunity/sonoran/compare/v2026.09.27.2...v2026.09.29

## v2026.09.27.2 — 2026-09-27

1 pull request merged, 37 issues closed.

#### New features

- Batch 3 — units everywhere, phone layout, stats range, chat, nodes, traceroutes (38 issues) (#303) — done: #246, #249, #250, #251, #257, #266, #267, #268, #269, #270, #271, #272, #273, #274, #275, #276, #277, #278, #279, #280, #281, #284, #285, #286, #287, #288, #289, #290, #291, #292, #295, #296, #297, #298, #299, #300, #301
  A big usability batch. Units follow your setting everywhere, and phones get a sticky top bar, cards and bottom sheets. Statistics gets a date range, the dashboard counts a rolling 24 hours, and chat is simpler. Traceroutes and node pages are laid out better, and the node page's links read every traceroute. Desktop can collapse the sidebar to icons.

#### Known

- **The node page's "Links and routes" panel is slow on this instance.** It takes 7 to 29 s uncached, and the node page's health panel and charts wait for it. Most of that is two older queries that join `packet_seen` to `packet` over 30 days, run six times per request, not this release's change to read every traceroute (about 0.6 s of it). Repeat visits within the cache window are fast. It's filed as its own issue for the next batch, with the measurements.
- Checked in emulation only: real touch, iOS Safari toolbars, iPad Safari, VoiceOver, Windows High Contrast.

#### Issues

- Done: #246 The planner's typed heights read in metres while the rest of the site reads in feet
- Done: #249 test_tooltip_escaping cannot fail on a formatter that returns implicitly
- Done: #250 Nodes list pages on offset, which can skip a row once the page refreshes on a timer
- Done: #251 Applying a node filter hides the panel and drops keyboard focus to the document
- Done: #257 Node page: why many nodes show no furthest-heard distance, and what to show instead
- Done: #266 Mobile (P1): Map dots: give them a finger-sized hit area on touch screens
- Done: #267 Mobile (P1): Key touch sizing to `(pointer: coarse)`, not width
- Done: #268 Mobile (P1): Enlarge the fixed-size controls on touch
- Done: #269 Mobile (P1): Chat timestamps: a real tap target, and the exact time on tap
- Done: #270 Mobile (P1): Stop the map page scrolling itself on load, or say why it does
- Done: #271 Mobile (P1): A compact sticky top bar on phones
- Done: #272 Mobile (P2): Nodes list as cards on phones
- Done: #273 Mobile (P2): Firehose rows as cards on phones
- Done: #274 Mobile (P2): Traceroutes table: sticky first column and priority columns
- Done: #275 Mobile (P2): Fold page-head controls behind a *Filters* button on phones
- Done: #276 Mobile (P2): Make title-only meanings reachable by tap
- Done: #277 Mobile (P2): Load ECharts only on pages that draw a chart
- Done: #278 Mobile (P2): Dashboard stat cards as one compact row
- Done: #279 Mobile (P2): Move the drawer's Preset and Settings above the fold
- Done: #280 Mobile (P3): A "N new" pill on the firehose when scrolled away from the top
- Done: #281 Mobile (P3): Map node detail as a non-modal bottom sheet on phones
- Done: #284 Mobile (P3): Reduced motion for charts and map zoom
- Done: #285 Mobile (P3): A `prefers-contrast: more` block
- Done: #286 Mobile (P3): Node page: in-page navigation on phones
- Done: #287 Mobile (P3): iPad portrait: fix the node page's three-column squeeze
- Done: #288 Traceroute detail: put Route, Path There and Path Back as the three widgets on top (feature)
- Done: #289 Traceroute detail: make "Open this trace in the mesh-graph" a button at the top right of the drawing (feature)
- Done: #290 Node page: Links and routes reads only the newest 2,000 traceroutes; read the whole window (feature)
- Done: #291 Units: Statistics is stuck in km; convert every distance and temperature site-wide from Settings (bug)
- Done: #292 Dashboard: show the four headline stats over a rolling last 24 hours (feature)
- Done: #295 Chat: take the date range off the main chat page; channel pages keep theirs (feature)
- Done: #296 Dashboard: clean up Latest messages, show 5, add a View all messages button to Chat (feature)
- Done: #297 Chat: MediumFast "view all" loads only by scrolling, overcounts, and the table view cannot load more (bug)
- Done: #298 Nodes list: column-header tooltips make the table scroll sideways (bug)
- Done: #299 Page headers: Coverage and Graph wrap the title and controls onto two lines (bug)
- Done: #300 Sidebar: let desktop users collapse the navigation to icons only (feature)
- Done: #301 Nodes list: the filter badge shows 2 on first load when no filter is selected (bug)
- Worked on: #294 Statistics: add a date-range control with quick buttons, default last 30 days rolling (feature)
- Worked on: #261 Review the whole site for phones and tablets, and research current mobile UI patterns

#### Thank you

- **Will**, for the reports behind this batch and for answering the open questions.
- **@logans-stuff**, for the CI hardware, and the runs that caught two layouts that only broke on Linux fonts.

**Full changes:** https://github.com/ArizonaMeshtasticCommunity/sonoran/compare/v2026.09.27...v2026.09.27.2

## v2026.09.27 — 2026-09-27

**`main` now matches the live site.** PR #302 merged the batch released as [v2026.09.26.2](https://github.com/ArizonaMeshtasticCommunity/sonoran/releases/tag/v2026.09.26.2) into `main`, and s.azmsh.dev was redeployed from `main` (4bd8b97) on 2026-09-27 at about 07:30 UTC. From here on, deploy from `main` again.

#### Fixes

- **Node page, "Who hears it" on phones:** at 320 px the table no longer scrolls sideways on devices whose fonts run wider. The headings can put their info mark under the word, and "about" in an estimated distance can move to its own line. A number always stays with its unit. (#260)

  CI caught this on the merge PR: the table fit to the pixel on macOS fonts and overflowed by 15 px on the Linux runner. The e2e journey now also measures with wider letters, so it fails on any machine, not only one with wider fonts.

#### Maintenance

- CHANGELOG.md, DECISIONS.md, and the #252 recovery tool's instructions (run it as the migration role, not as ingest) are now on `main`.

#### Thank you

- **@logans-stuff** for okaying the CI runs, on his own hardware, that caught the 320 px overflow before it merged.

## v2026.09.26.2 — 2026-09-26

**Deployed to https://s.azmsh.dev on 2026-09-27 at 05:22 UTC**, from branch `batch/v2026.09.26.2` (01d2b3b). CI on this project runs on a community member's self-hosted hardware, so the release was published from the branch first. The branch then went to `main` as a single pull request, once the hardware's owner okayed that CI run.

#### The big one: three days of signed packets, recovered

From **2026-09-23 22:43 UTC**, every packet from a node that signs its traffic was decrypted correctly and then stored as unreadable. That was 49 senders, including all of NGSP's telemetry. It's why Sonoran showed NGSP three days behind Meshview.

- **Cause.** Meshtastic added a signature field (`Data` field 10, `xeddsa_signature`). Our vendored protobufs predated it. Our stricter decryption check requires every field of a decrypted packet to be known, so it rejected every signed packet as a wrong-key false positive.
- **Fix.** The protobufs are regenerated from meshtastic/protobufs **v2.8.0**. The strict check stays: a field no `Data` has still fails. A canary test fails the build if the schema ever loses field 10 again.
- **Recovery.** The rejected packets were never thrown away, because ingest keeps raw bytes. A new backfill, `python -m sonoran.ingest.recover`, re-reads them through the live decrypt, decode and store path. On production it **recovered 1,832 packets**:
  - 602 telemetry
  - 479 NodeInfo
  - 312 text
  - 174 neighbor info
  - 144 positions
  - 121 others

  1,214 packets stayed unreadable. Those are genuinely on channels this instance holds no key for, and their rate matches what the fixed ingest now rejects live (about 2 to 3% of traffic). A second run recovers nothing. A database dump was taken first.
- **Not recovered:** the per-packet radio metrics for that window. They are computed from the MQTT message's size on the wire, which wasn't stored.

(#252)

#### New features

- **Weekly check-in** now reads MediumFast only. It shows the streak as a pill beside each name, not in orange, and hashtags aren't orange any more. (#262)
- **Gaps page.** Every value now carries its unit, so it reads "Yes (22.6%)" rather than "Yes 0.226". The table also has a key. (#265)
- **Node page, Identity and Device.** "Unknown" is capitalised, bad values are flagged in red, and every field has an info tooltip written for newcomers: MQTT gateway, Licensed, Hardware, channel use, TX air time and the rest. (#254, #256)
- **Node page, furthest heard.** The tiles give an estimate with its range, or say why there isn't one, instead of going blank. (#257)
- **Node page, packets.** The explanation moved into a tooltip and the controls moved to the top right. "LAST 720 H" is gone, and the timeline keeps loading as you scroll, using a cursor so pages never overlap. (#259)
- **"Open in mesh-graph"** is now a button. (#258)

#### Fixes

- **Map:** a node's info bubble no longer closes every time live traffic refreshes. Markers now update in place. (#264)
- **iPad:** the page colour now fills the ~25px band that appeared when you overscroll past the top, in both themes. (#253)
- **Node page:** the Activity and "Who hears it" tables fit their panels at every width, with no sideways scroll. (#255, #260)
- **USB config read:** the serial descriptor is regenerated from protobufs v2.8.0. This is related to the firmware 2.8.0 "invalid wire type 7" report, but it is **not** a fix for it. That error comes from the separate cfgtest tool: it reads the serial port as text and falls back to a binary guess, and never uses the `want_config` handshake. The issue has the whole trace. (#263)
- **Backups:** these had been failing since 2026-09-25 because of TOAST corruption in one `rf_spectrum` chunk. 1,074 of its 1,085 rows were salvaged row by row, and the chunk was replaced in one guarded transaction. Dumps succeed again. Still open: the container's healthcheck did go `unhealthy`, but nothing routes that to a person. (#244)

#### Maintenance

- **Frontend lint in CI.** ESLint `no-undef` now catches a reference to a deleted name before it reaches a reader's browser. Six such bugs got through in one session. The shared global names are derived from the scripts on every run, never hand-listed, so deleting a function fails every remaining caller. It runs inside the existing lint job, so no new runner. (#248)
- **Release process.** `tools/release.py`, `docs/RELEASING.md`, a PR template and CHANGELOG.md. Changelog headings now use the Arizona date, matching the tag.

#### Documentation

- A mobile and tablet review of the whole site, with measurements, a prioritised list and research on current patterns: `docs/design/2026-09-27-mobile-review.md`. (#261)
- `docs/DECISIONS.md` records why this batch was released and deployed from a branch.

#### Known and pending

- The recovery tool has to run with the migration role's database URL, not as ingest: the ingest role is write-only by design. The docstring says so (f9f3d4b, docs only, merged with this batch).

#### Thank you

- **Fernando** for spotting that NGSP was three days behind Meshview (#252), and for the firmware 2.8.0 USB report with its exact error and offset (#263).
- **StarSkream** for the map bubble that kept closing (#264) and the gaps page's raw fractions (#265).
- **Will** for the long, specific list behind the node page, iPad, check-in and mobile work (#253 to #262).
- **@logans-stuff** for the self-hosted hardware every CI run here uses. Keeping this batch off it until the freeze lifts is the point of releasing from a branch.

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
