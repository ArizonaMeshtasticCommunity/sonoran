# Decisions

Calls made while working this repo, with the evidence behind them and
what would change the answer. One entry per decision.

**Why this file exists.** A decision with no recorded reasoning is one
that gets re-litigated or silently reverted — usually by somebody
reading the same issue that prompted it and reaching the same first
conclusion. The output is not the valuable part; the reasoning is.

Where a decision has a tripwire, the test is named. A decision nothing
holds is a preference.

---

## Data and what the dashboard may claim

### A link we have barely seen is `unknown`, not `weak` (#149)

**Decided:** rename the low-evidence state end to end. No threshold
moved; nothing was reclassified.

The graph labelled **90% of links at 24 h** "Weak link: few packets
crossed it", while the legend under it read "Weak: under 10 packets
seen" — a claim about the *link*, justified by a fact about our
*evidence*. #87 was the same confusion facing the other way, where a
node nothing had heard rendered as healthy.

**Breaking:** `strength` on `/api/graph` and `/api/graph/link` returns
`"unknown"` where it returned `"weak"`. No soft landing exists that
also fixes the bug — continuing to emit `"weak"` preserves the exact
falsehood the change removes.

### The threshold is NOT scaled by the window (#149)

**Decided:** leave the fixed count of 10, and say so in the code.

A fixed count across a 1 h–168 h window means the label partly reports
the reader's choice: 97.0% / 90.0% / 69.5% unknown at 6 / 24 / 168 h.
The obvious fix is a rate — ten per 24 h, scaled. **Measured, that is
worse:** 79.4% / 90.0% / 96.4%. It inverts the dependence rather than
removing it, because the link *population* grows with the window too
(1,219 links at 6 h against 4,964 at 168 h, mostly links seen once).

**What would change it:** a different definition of link strength —
something per unit time, or a confidence rather than a count.
**Tripwire:** `test_the_threshold_is_not_scaled_by_the_window`.

### A link's SNR is the median, not the newest reading (#71)

**Decided:** median of every sample in the window.

It kept the newest and discarded the rest, so the number moved with
whichever hop happened to be measured last. Not the mean (dragged by
the outliers a shared channel produces constantly) and not the maximum
(that is `best_snr`, which answers "how good can this link get").

**Honest about size:** of 18 links with 10+ readings, 12 differ by
≤0.5 dB. The dramatic case — one link reading −6.75 dB against a −16.0
to −0.25 spread — is the tail, not the rule. Worth doing because 3 dB
separates a link that carries from one that does not, and a median
cannot be moved by measurement order.

### NeighborInfo is not demoted (#90)

**Decided:** treat a neighbour report as the same class of evidence as
a traceroute hop.

The question "is it a link or a neighbour table?" contains a false
dichotomy. A neighbour table is built from packets the node actually
received, so an entry is evidence a packet crossed the link — with no
guarantee about *now* or about both directions, which is exactly a
traceroute hop's status.

Measured: neighbour and traceroute recency interleave (7 of 15 links
have the *newer* evidence from NeighborInfo, middle of the distribution
around ±4 h). Neighbour-only links reach traceroute corroboration at
0.57× baseline; traceroute-only links reach neighbour at 0.24×.

**Bound worth knowing either way:** 51.4% of neighbour-only links never
see a traceroute over a 7× window. **Unresolvable confound:** traceroute
sampling is not random, so "never corroborated" conflates "does not
carry" with "nobody traced it".

### The live map draws hop COUNT, never an inferred hop (#47)

**Decided:** ship option 1 (already shipped), decline option 3.

`relay_node` carries only the **low byte** of the relayer's node
number: 131,052 rows over 7 days, every value under 256, 4.91
candidates per byte on average and 19 at worst. The byte alone resolves
about 3% of nodes.

AGENTS.md 9.5: a speculative hop between the wrong pair of nodes is
worse than no line at all, because people plan antennas from this map.

**What would change it:** upstream carrying a full relayer id, or a
measured narrowing that collapses the candidate set to one for a useful
share of packets. **Tripwire:**
`test_live_map_draws_no_inferred_hop.py`.

---

## Interface

### Panels stop growing on a wide screen, via the GRID not the track (#70)

**Decided:** cap the grid container, leave the track `1fr`.

At 3840 px the four stat tiles were 872 px each, because `auto-fit`
collapses tracks it cannot fill. Capping the **track** also fixes 4K —
and breaks 1440, taking the dashboard from four columns to two, because
`auto-fit` computes its repetition count from a definite max track
size. **Tripwire:** `test_the_track_is_still_a_fraction_and_not_a_fixed_ceiling`.

Maps are deliberately not capped: the same issue opened with "map
should probably fill the whole div".

### The health summary sits above the node map (#95, #103)

**Decided:** identity row, health, then map.

Both issues were individually satisfied and **jointly** put the health
summary at y=1069 on a 1440×900 laptop — below the fold, a milder form
of the complaint #95 was filed about. Neither issue describes the
result. Found by re-measuring an acceptance criterion already declared
met.

**Standing rule from it:** an issue is complete when its acceptance
criteria hold on the *running* thing, not when the diff implementing
them merged.

### The gaps page never honoured that setting (#177, follow-up)

**Reported:** the gaps page defaulted to LongFast.

**The default was never wrong.** `_resolve` took `listed[0]` from the
gaps index, and `jobs/gaps.py` writes that index in **channel-name
order** — so "LongFast" sorted above "MediumFast" and the first entry
was an accident of the alphabet. Measured on the live instance before
the fix: LongFast selected, with **309 assessed nodes against
MediumFast's 763**. The page opened on a preset carrying under half the
mesh.

Two other pages had already met this. `coverage.js` carries a comment
describing the identical bug and picks the busiest preset instead;
`leaderboards.py` had the full preference logic from #177. The gaps page
had neither, and each of the three had its own copy of the ordering.

**Decided:** the ordering lives once, in `gaps.store.assessed_presets` —
`default_preset` first when it was assessed, then by node count — and
both routes read it. A test holds the two routes to the same answer,
because three copies of one sort is how only one of them got fixed.

Also removed `DEFAULT_PRESET_KEY = "LONG_FAST"` from `radio/presets.py`.
It had no consumers, contradicted the setting decided in #177, and a
constant sitting beside a setting is a second answer to one question
waiting for somebody to reach for it.

**Standing rule from it:** when a fix is about ORDER, the fixture has to
reproduce the real order. Two of these cases first used counts where
by-count and alphabetical happened to agree, so deleting the node-count
sort left them green. The mutation check found that, not the tests.

### The preferred preset is a setting, not a constant (#177)

**Decided:** `DEFAULT_PRESET`, defaulting to `MediumFast`, falling back
to previous behaviour wherever that preset is absent.

The preference belongs to a deployment — another mesh running LongFast
should not patch code to land on it. The fallback matters more than the
preference: a preset that was never assessed must not put an empty page
in front of anybody.

### One live region, in the bar, never visible (#175)

**Decided:** the status text moves into the menu; the live region does
not.

The menu is `hidden` when closed, which removes its contents from the
accessibility tree. The status line is the only live region on this
site. Moved naively into the menu it would stop announcing the moment a
phone user closed it, **and nothing would look wrong**. **Tripwire:**
`test_the_live_region_is_not_inside_the_menu`.

### A reported neighbour is named by the API, not by the browser (#240)

**Decided:** join the name server side, in `_decoded_payload`, and add
`neighbor_id` and `neighbor_name` to each row of the `neighbors` kind.

The packet page printed `!0a51a002` for each node a neighbour report
named, while "Who heard it" — the panel directly above it, on the same
screen — printed "Usery Pass Relay" for that same node. The bug was not
a missing lookup. The cell built the ID and then passed it as the
display name, so a name would have been discarded even if one had been
there.

The browser holds no node table, so naming them there needs one request
per neighbour, and the gateway rows beside them are already named by
`resolve_names`. One query for the whole list is the cheaper half of
that comparison, and it puts both answers on one code path. The query
is asked **only** for the `neighbors` kind: no other decoded family
points at a second node, and adding it to all of them would put a
pointless query on every telemetry packet page.

`name_of` already falls back to the ID form, so the "no long name"
case the issue asks about is answered once, server side, rather than in
every consumer. **Tripwires:**
`test_a_reported_neighbour_carries_its_long_name`,
`test_no_other_decoded_family_pays_for_the_name_query`,
`test_printing_the_id_as_the_name_would_be_caught`.

### The visible spelling is "neighbor", the names keep theirs (#240)

**Decided:** every sentence a reader sees says "neighbor". Every
identifier keeps the spelling it had.

`labels.js` used to record the opposite call: British, to match the rest
of the interface and the mesh-graph legend in the embed. #240 asked for
the American spelling, and a half-done change is worse than either
spelling — a page that says "Neighbor info" in the firehose and
"Neighbours it reported" one click later reads as two products. So all
of it moved together: the packet page, the node page panel and hints,
the map and graph legends, the coverage empty state, the firehose
summary line, the config-check field label, and the gaps reason
sentences.

Nothing else moved. `neighbor_metrics`, `neighbor_node_num` and
`NEIGHBORINFO_APP` are the protocol's and the database's own names.
`neighbour_reports`, `best_neighbour_snr` and `no_neighbour_reports` are
internal keys of the gaps evidence object, `named_as_neighbour` and
`neighbourValues` are private symbols, and `.line.neighbour` is a CSS
class. Renaming any of them would change an API response or a stored
artefact to fix a spelling on a page, which is a wire break for a
cosmetic gain. The mesh-graph legend in the iframe still says
"Neighbour report" and is a separate application. **Tripwire:**
`test_the_british_spelling_coming_back_would_be_caught`.

---

## Safety and privacy

### Bad `meta` fields are filtered, not rejected (#148)

**Decided:** filter per key rather than raising.

Observations arrive in batches of 100. One bad field rejected the whole
batch, so a deployed station with one malformed value would have gone
silently dark.

### `/api/graph` clamps rather than refusing (#148)

**Decided:** accept `hours` up to 720, clamp to 168, and say so in
`window_clamped`.

A caller whose script says `hours=720` was inside the documented range
yesterday. Breaking it to protect our own box is the wrong trade when a
softer one exists.

### The diagnostics report is imported, not reimplemented (#119)

**Decided:** import upstream's module unchanged.

Its privacy model is a **whitelist** — assembled field by field, with
no path that copies a caller-supplied object wholesale. Rewriting it
means rewriting the guarantee, and a blacklist written from memory is
how PSKs end up in bug reports. Verified with a planted PSK-shaped
secret: it appears in neither the report nor the filename.

### The MQTT password is never stored (#118)

**Decided:** field → downloaded file, nowhere else. No "remember me".

This page's whole promise is that nothing leaves the device, and a
stored broker password would be the one thing on it worth taking.

### Two vendored CVEs are guarded, not bumped (#174)

**Decided:** tests that fail when the condition becomes reachable.

CVE-2026-45249 (ECharts XSS) needs a `lines` series, which this repo
does not use — and which is one ordinary feature away, since link paths
on a map is the obvious next thing. CVE-2026-59877 (protobuf.js DoS)
needs `.proto` schema *text*; every call site uses `Root.fromJSON` on a
static descriptor. Both tests relax themselves once the vendored
version passes the fix.

---

## Process

### Issues are not closed on the author's behalf

A tracker entry is a maintainer's record of what they asked for, not a
checklist for whoever wrote the code. Issues filed by others are left
open with a comment saying what landed and what was measured.

### Security changes ship in their own PR

A security change reviewed alongside features stops being reviewable.
Where one merges without human review, that fact is stated on the PR
rather than left to be inferred.

### Verification beats reasoning

Recurring failure this repo has hit in several costumes: a skipped test
read as passing, an absent log line as a clean run, a capped counter as
no new runs, an empty `projectItems` as "not on a project", a negative
search result reported as a fact about the codebase.

**In every one the reasoning was sound and the instrument was lying.**
Judgement does not protect against that; only a measurement can be
wrong out loud.

- A gate result is a claim about a **moment**, not a property.
- An empty result and a true negative are indistinguishable until the
  instrument is proven — show it can find something known to be there.
- Your own past claim is the same shape as a green check.

### The cfgtest link is reworded, not removed (#115)

**Decided:** point the USB sentence at this page's own control, and
keep cfgtest named as a fallback.

The old sentence — "cfgtest.azmsh.dev reads the config straight off it,
with no export step" — became **false** the moment #116 and #117
landed, so leaving it was not neutral.

#115 asks for the link to be removed entirely once parity is reached.
It is not removed, and the reason is specific rather than cautious:
**cfgtest's USB path has been used against real boards and this one has
not.** Every other row of the parity table is closed; this one rests on
a simulator, and a simulator cannot reproduce how a driver splits
reads, how fast a board answers, or what an nRF52 does that an ESP32
does not.

Removing the fallback would be promising parity that nothing has
checked, to people who would then have nowhere to go when it failed.

**What would change it:** `docs/USB-HARDWARE-TEST.md` coming back clean
on one ESP32 and one nRF52. Then the sentence loses its second half and
#115 closes with it.

### "Needs hardware" was partly a failure to look (#116, #117)

**Decided:** verify the protocol against `meshtasticd` — the real
Meshtastic firmware — and reserve the hand-test for what only a board
can show.

I asserted for a long stretch that these issues were blocked on
hardware I do not have, and built a simulator instead. `meshtasticd`
runs the actual firmware and speaks the same client API over TCP. It
was one `docker pull` away the whole time.

**What that cost.** The simulator passed a write path that **silently
does nothing**. An `AdminMessage` must be wrapped in a `MeshPacket`
addressed to the local node on the admin port; sending it bare is
accepted by the firmware and ignored. The write reported `wrote 1`, the
UI would have said "Wrote 1 setting", and a re-read showed the old
value. No error anywhere.

**All 22 write tests passed against the broken version**, because a
simulator checks what we *send*, not what a node *does* with it. The
tests were not wrong; they were measuring the wrong side of the wire.
And I built the instrument.

The generalisation, which is the same one this file already records in
another costume: **a test you wrote against a model you wrote can only
find the bugs you thought of.** Before accepting "this can only be
verified with X", ask what the nearest real implementation is. Often it
ships in a container.

**What remains genuinely hardware-only:** the USB transport — CDC-ACM
chunking, the reboot a commit triggers, port release, nRF52 against
ESP32. That gap is real, and much narrower than "needs a board".

### The integration suite is made to run locally, not routed around

**Decided:** turn testcontainers' reaper off in
`tests/integration/conftest.py`, and set `SONORAN_REQUIRE_INTEGRATION`
in the `test` job so a container that will not start is red.

All 166 database-backed tests skipped on any Mac running Colima. The
cause was already written into the conftest docstring — testcontainers'
Ryuk sidecar bind-mounts the Docker socket, and Colima's socket sits on
a virtiofs mount where that is "operation not supported" — and the
response at the time was a documented workaround: start a Postgres
container by hand and point `SONORAN_TEST_DATABASE_URL` at it. The
one-line fix, turning the reaper off, was never tried.

That is the same mistake as the USB work above, in a second place: the
boundary was diagnosed accurately and then **defended rather than
tested**. A correct diagnosis is not a reason to stop.

**Measured, three arms on one machine:**

| reaper | guard | result |
|---|---|---|
| on | off | 14 skipped — the false green, and how it looked for months |
| on | armed | 14 failed, message naming the variable |
| off (the fix) | armed | 166 passed |

**What the guard is for.** pytest prints a skip and a pass on the same
summary line, so losing 166 tests looks identical to running them. CI
does run them today — run 35914127599 reports `1516 passed, 1 skipped`
— so this was local blindness and not a CI hole, which is worth stating
plainly because the first version of this note claimed otherwise before
the log was read. The variable makes CI's green mean "they ran" rather
than "nothing objected".

**The cost, stated:** without Ryuk, a test run killed outright can
leave one container behind. `timescale_url` already stops the container
on every ordinary exit, so the reaper was only ever insurance against
the abnormal one — and it was charging every local run for it.

**What would change this:** a Colima release that can bind-mount its
own socket, or a testcontainers reaper that does not need one.

**Held by:** `tests/unit/test_integration_suite_runs.py`, which calls
both helpers rather than grepping for them, and covers the spellings of
the variable a workflow might use.

### Why a payload could not be read is recorded, not inferred (#157)

**Decided:** add `packet.payload_state`, set at ingest on all three
paths, with no backfill and no default argument.

**The measurement that drove it.** `tools/portnum_zero_census.py`
against production, 168 h:

| what a `portnum = 0` row actually was | count | share |
|---|---|---|
| PKI — a direct message nobody here could read | 8,342 | 91.7% |
| no key we hold opens it | 743 | 8.2% |
| a key opened it, real payload | 7 | 0.1% |
| a key opened it, empty payload | 1 | 0.01% |

Corroborated against something that does not read the same bytes: 99.5%
of those rows are addressed to one node, against 35% of all other
traffic. The control fires, so "addressed" is a property of *these*
rows and not of packets generally.

**This overturned the issue.** #157 was written around a wrong-key
false-accept rate of roughly 1 in 800, and around 8,841 real packets a
week as the cost of rejecting portnum 0. The real false-accept
population at portnum 0 is **one packet a week**. The proposed
empty-payload rejection rule is therefore dropped: it was designed
against a problem that is not there, and a rule in the decrypt path
should not be paid for one packet a week.

**The real harm was the label**, and it is worse than the issue thought:
that bucket is ~99.9% mislabelled, read by operators deciding what
their mesh is doing.

**Three decisions inside the change.**

*Not called `payload_readable`.* The plan named it that. A three-valued
answer must not wear a boolean's name — that is the same mistake as the
label it fixes, and the one #149 made calling an unmeasured link weak.

*No default on `_store_opaque`'s new argument.* Defaulting to `NO_KEY`
would read fine and let a fourth caller silently record the wrong
reason, which is precisely the failure this column ends.

*No backfill.* The answer for an old row is in `raw_bytes` and needs a
decryption attempt per row against the current keys — which would write
today's key configuration onto packets ingested under a different one.
NULL means "nobody asked at the time" and readers must show it as
unknown rather than fold it into the commonest value.

**What would change this:** a firmware that exposes the port number
outside the encrypted part, which would make the whole column moot.

**Held by:** `tests/integration/test_ingest_pipeline.py` replays one
recorded packet down all three paths and asserts both that the reasons
differ **and** that `portnum` still cannot separate them — the second
is what makes the column necessary rather than merely present. Proven
by mutation: mislabelling the PKI arm turns it red.

**Two instrument failures caught while writing it**, both worth keeping:

- The first version of the three-arm test stored one row and measured
  it three times. Deduplication is on `(from_node_num, packet_id)` and
  does *not* include time, so arms two and three were dropped. The
  assertion that caught it was `len(rows) == 3`, which only existed
  because the arms were counted rather than assumed.
- The first mutation test **passed**, which would have been reported as
  "the test is sound". It had not run: `sed` matched `PayloadState.PKI$`
  and ruff had reformatted the line to end in `)`. A mutation that does
  not apply is indistinguishable from a mutation the test survives.
  Always confirm the mutation landed before trusting its verdict.

### The unreadable bucket is named for what it is (#157)

**Decided:** `traffic_label(portnum, payload_state)` replaces the three
identical `_portnum_name` copies in the route modules, and port 0 now
resolves to one of four names instead of always `UNKNOWN_APP`.

| stored row | was drawn as | now |
|---|---|---|
| PKI direct message | `UNKNOWN_APP` | Direct message, encrypted |
| no key for the channel | `UNKNOWN_APP` | No key for this channel |
| readable, port really 0 | `UNKNOWN_APP` | Unknown |
| stored before 0015 | `UNKNOWN_APP` | Unreadable, reason not recorded |

**The fourth copy stays.** `decode/payloads.py` answers `UNKNOWN_{n}`
where the route copies answered `str(n)`, because it names a decoded
payload rather than a chart band. Merging two different contracts to
make a count of duplicates go down would be a change nobody asked for.

**The new names are kept out of `PORTNUM_LABELS`.** That table is read
*backwards* by `portnumWire`, which turns what somebody types in the
firehose filter into a value the API accepts. `UNREADABLE_PKI` is not a
port number and the API answers 422 for it, so putting the new names
there would offer the filter three phrases that cannot work — a bug
nobody finds until somebody types one. They live in `TRAFFIC_LABELS`,
which `portnumLabel` reads and `portnumWire` does not.

That risk is what the browser tests are built around: the mutation they
run is not a broken lookup but **the plausible, tidy-looking refactor**
— moving the entries into the port table — and the cases go red on it.

**What would change this:** firmware exposing the port number outside
the encrypted part, which would retire the whole mechanism.

**Held by:** `test_traffic_labels.py` (the helper, including that a
real port is untouched whatever the state says, and that NULL is not
folded into the commonest value); `test_traffic_labels_in_the_browser.py`
(the shipped `labels.js` run under node, with both mutations);
`test_api.py::test_port_zero_is_no_longer_one_bucket_called_unknown_app`
(the endpoint, which is the only place that can show the `group_by`
carries the state far enough for a name to be chosen — proven by
mutation against the old single-column grouping).

**One thing this got wrong first.** The endpoint test seeded a node and
left it there. The container is session-scoped, so two siting tests went
red on a node they never seeded. A fixture that only ever adds rows is a
slow-acting failure in whatever runs after it; it now cleans up in a
`finally`.

### CLIENT is a role, and was being stored as silence (#197)

**Decided:** do **both** options the issue offered, in that order — fix
the ingest so new rows are right, and resolve old NULLs in one place.

`store_nodeinfo` read every enum with `if not value: return None`, and
Meshtastic numbers `CLIENT` as zero. So the commonest node on the mesh
was stored exactly like a node that had never spoken.

**Measured on production before the fix:**

| | |
|---|---|
| nodes total | 2,497 |
| `role = 'CLIENT'` | **0** |
| `role IS NULL` | 1,680 |
| …of those, carrying a name | 985 |

Zero is the whole argument. In the entire history of this database, the
default role of a Meshtastic node has never once been recorded.

**Why both halves.** Fixing ingest cannot repair old rows — nothing in
the database says which NULLs were clients — and waiting for every node
to re-announce would leave the map wrong for days. Resolving old NULLs
alone would leave ingest still manufacturing them.

**The inference, and its limit.** `resolve_role` reads a stored
`long_name`/`short_name` as evidence a User message was processed,
because `store_nodeinfo` writes those in one statement with the role
and nothing else in the ingest writes either field — checked, not
assumed. It lives in `roles.py` only, so a second page cannot grow a
version that disagrees, and it **expires**: the set it touches only
shrinks as nodes re-announce.

**An unknown role now keeps its digits** (`ROLE_<n>`) instead of
becoming NULL. Collapsing an unvendored role into NULL would feed it
straight back into the bug being fixed. This is not hypothetical —
`CLIENT_BASE` (12) was unvendored until recently, and the first draft
of the test used 12 as its "unknown" example and failed, because the
proto already knew it. The test now computes the first unvendored
number from the descriptor, with a positive control that the number it
picks really is unknown.

**`_enum_name` keeps treating zero as None**, and should: `hw_model`
zero is `UNSET`, which genuinely means nothing was reported. Fixing
role through the shared helper would have made every unset hardware
model read as whatever name zero carries.

**This is the third instance of one pattern** — #157 (portnum 0 is both
a real port and a sentinel), #149 (an unmeasured link labelled weak),
and now this. The shape: *a value that means "absent" sharing storage
with a value that means something*. Worth looking for a fourth.

**Held by:** `tests/unit/test_client_is_a_role_not_a_silence.py`, which
builds real `User` protobufs rather than mocks — the bug was in how a
protobuf's defaults read, so a mock with a `role` attribute would
reproduce the reasoning and not the bug.
### A job the kernel kills must not become a livelock

**Decided:** record that a task was *attempted*, across restarts, and
let `at_start` mean "if it is actually due".

**What was happening on the dev box.** The coverage job is killed by
the OOM killer part-way through every run. `unless-stopped` restarts
the container, `at_start` re-runs coverage immediately, and the kernel
kills it again:

```
21:16:39  coverage starts
21:20:01  removed a coverage run that never finished
21:24:51  jobs running: ...            (restart)
21:24:56  removed a coverage run that never finished
```

Eleven restarts in one stretch. **Coverage has not completed once** —
the last finished run on disk was 2.5 hours old when this was found.

**The cost was not the wasted work.** The storm starved the thing
people look at. Measured on that box minutes apart:

| endpoint | jobs stopped | jobs running |
|---|---|---|
| `/api/graph` | 0.32 s | **2.06 s** |
| `/api/nodes?limit=300` | 0.04 s | 0.22 s |

**The record is written before the run, not after**, and that is the
whole design. A process killed part-way through never reaches an
"after"; a success-only record would stay empty for ever on precisely
the deployment that needs the backoff, and the livelock would continue
behind a passing test. Proven by mutation: moving the call after
`task.run()` turns the ordering case red.

**What this does not fix.** Coverage still cannot complete on this box
— 3.4 GB RAM with swap pinned at 2047/2047 MB for an entire run. This
makes it fail once an interval instead of continuously, which gives the
CPU back to the API; it does not produce a coverage map. That needs
either less memory in the prediction or more memory in the box, and the
box is the owner's call.

**A correction I had to make to this entry.** It first said the box has
**one core**, and everything above was written around that. It has
**three**. The claim came from `nproc`, read once and reused: `nproc`
returns 1 on that host while `nproc --all` returns 3, the containers
see 3, and CPU affinity is `0-2`. I have not explained the discrepancy
and am not asserting a cause.

Nothing else in this entry changes, and the reason is worth keeping:
the slowdown was **measured** (0.32 s against 2.06 s, load average
20.9) rather than derived from a core count. A conclusion resting on a
measurement survived a wrong fact underneath it; one resting on the
core count would not have. It is the fifth instrument failure in this
session — after `.State.ExitCode` on a running container, `$?` after a
pipe, a `sed` that matched nothing, and a literal that ruff had
reflowed.

**Two instrument failures worth keeping.**

- `docker inspect --format '{{.State.ExitCode}}'` on a **running**
  container reports `0` — the code of the container now, not the code
  it last exited with. That sent me looking for a silent clean exit
  that never existed. The real answer, from a foreground `docker run`,
  was **137**: SIGKILL.
- `echo "EXIT=$?"` after a pipe reports the *last* command's status, so
  a probe piped into `tail` reported the exit code of `tail`. It said
  `EXIT=0` for a container that had been killed. Use
  `${PIPESTATUS[0]}`, or do not pipe.

**Held by:** `tests/unit/test_jobs_survive_being_killed.py` — ten cases
including that a fresh box still runs at once, that a genuinely due job
still runs, that a corrupt or unwritable record costs the backoff and
never the process, and the ordering, checked against comment-stripped
source.

### A telemetry field the node did not send is not a reading of zero (#190)

**Decided:** store `None` for any telemetry field the protobuf says was
not present.

`store_telemetry` checked `HasField` for the *message* and then copied
every *field* without a check, so an absent field's default landed in
the database as a measurement. A node with a temperature-and-humidity
sensor and nothing else was recorded as reporting a barometric pressure
of 0 hPa — not a low reading, not a pressure at all.

**Measured on the live database, seven days, before the fix:**

| | rows | field = 0 | field IS NULL |
|---|---|---|---|
| `environment_metrics.barometric_pressure` | 5,811 | **2,642 (45%)** | **0** |
| `device_metrics.voltage` | 17,713 | 1,255 | **0** |

The zero NULLs are the proof. With per-field presence working, some
node somewhere would have to be missing something.

**A real zero is kept.** Turning every zero into None would be a
different lie in place of the old one: a node at freezing reports 0 °C,
a flat battery reports 0%, a dry hour reports 0 rainfall. That is the
obvious wrong implementation, so it has first-class tests rather than a
remark.

**`HasField` raises on a repeated field** — `one_wire_temperature` is
one — so those keep their value. None are stored today; the branch
exists so adding one cannot take the ingest down with a `ValueError`.
My first test for it asserted `== 0.0`, assuming a field `HasField`
refuses must be a scalar without presence. It is a list. The code was
right and my expectation was wrong.

**This is the fourth instance of one pattern**, after #157, #149 and
#197: *a value meaning "absent" sharing storage with a value that means
something.* Four is no longer a coincidence. Worth a standing check on
any new column: what does the absent case store, and can it be told
from a real one?

**Held by:** `tests/unit/test_a_field_not_sent_is_not_a_zero.py`,
including an invariant that every field this handler stores still
supports presence — so a schema change that silently removed it turns
the suite red rather than quietly restoring false zeros. Proven by
mutation: forcing `present = True` reproduces the bug and turns two
cases red.

**Not backfilled.** The false zeros already stored cannot be told from
real ones without the original packets, and `raw_bytes` holds the
MeshPacket rather than a decoded telemetry row. Readers should expect
old rows to carry them.

### "View all" is only said when it is all (#200, with #193.5)

**Decided:** fix #200 and #193 item 5 in one change, because doing
either alone makes the page worse.

#193.5 asked for the "N more" span beside the button to go, since "the
button already gives the total". #200 then showed that the button's
total is **a lie whenever the API caps the list**: "View all 25
messages" on a node that had sent 1,184. Removing the span on that
justification, alone, would have left the page asserting a wrong number
with nothing beside it to hint otherwise.

That is the #95/#103 shape again — two issues each individually
satisfied, jointly producing something neither described. It is the
second time in this repository, so the rule is now explicit: **before
closing an issue that removes a signal, find what else was relying on
it.**

**The audit #200 asked for**, every `expandingList`/`expandingTable`
caller:

| caller | data | capped by the API? | now says |
|---|---|---|---|
| `messagesPanel` | `messages.recent` | **yes**, 25 of a measured `count` | "Show the 25 newest messages" |
| `neighborPanel` | `neighbors` | limit 100, **never reached** | "View all N nodes" |
| `heardByPanel` | gateways | no | unchanged |
| routes `heard_by` / `hears` | no limit | no | unchanged |
| chat sections | — | already compared `count` with the list | unchanged |

**The neighbours cap was measured rather than fixed.** Over 7 days, 176
nodes report neighbours and the most any node has is **37**, against a
limit of 100. Building a truncation signal for a case that does not
occur would be work with no reader. If a node ever passes 100 this is
wrong, and that is written here rather than guarded, deliberately.

**The decision reads a measured count, not a heuristic.** "The list is
exactly 25, so it must be cut" would be wrong for a node that really
sent 25. `detail.messages.count` is measured by the endpoint and is the
only thing on the page that can tell a short list from a cut one.

**The true total stays in the heading.** The button now says "the 25
newest", so the heading is the only place that says 1,184; removing it
would trade a wrong number for no number.

**Held by:** `tests/unit/test_node_page_desktop.py`, including the
non-regression half — uncapped callers must keep "View all", or the fix
is a rename of every button on the site. Proven by mutation: forcing
`cut = false` restores the bug and turns the comparison case red.

### Prose moves behind a hint, guidance appears where a panel is empty (#191, #192)

**Decided:** extend #99's hint mechanism to panel headings, and move
only the prose that #191 allows.

**What moved:** the "Heard by" explanation of relayed versus direct
signal, the "Rounded by its owner" note, and the four route tiles'
`title` attributes. #99 removed `title` tooltips deliberately — a
finger cannot hover and a keyboard cannot reach one — and those four
tiles had kept theirs, so the only explanation of "Hops to the nearest
gateway" was invisible on a phone.

**What deliberately did not move.** Empty states, and any sentence that
changes what a number means. If the reason a figure is absent sits
behind a button, the figure reads as a fact — which is the bug #193.7
had just fixed, and sweeping it into a hint would have reintroduced it
in the same session.

**#192's ordering is decided by measurement, not taste.** Of 1,189
active nodes over 7 days:

| panel | empty | share |
|---|---|---|
| Device | 849 | 71% |
| Weather | **1,117** | **94%** |

At 94%, the common reason Weather is blank is **no sensor**. Guidance
leading with "enable environment telemetry" would misdirect roughly a
thousand owners toward a setting that cannot help them, so the sensor
comes first and a test asserts that ordering rather than trusting the
wording to survive an edit.

**Setting names are quoted, and checked.** From
`ModuleConfig.TelemetryConfig` in the vendored proto, with a test that
every name the guidance prints is a real field — otherwise the page
could name a plausible setting no firmware has and every other test
would still pass. No default interval is stated, because the proto
states none (AGENTS.md 9.27).

**One near-miss worth keeping.** The route tiles were first given the
`stat` class to reuse `revealHints`' existing selector. That looked
correct and was an accident: `.stat` and `.route-tile` have equal
specificity, so the tiles kept their padding and font size only because
`.route-tile` appears later in `app.css`. Borrowing a class for a
selector's side effect is a change that works until someone reorders a
stylesheet. The selector was broadened instead, and a test now forbids
the borrowed class.
### The live map opens on a region, and out-of-state nodes do not vote (#195)

**Decided:** option **(a)** of the two the issue put to maintainers —
open on the home region, and let the reader zoom out freely.

(b) was "stop the reader zooming out past Arizona", via `minZoom` or
`maxBounds`. That would hide the 148 out-of-state nodes completely, and
#114 says in as many words that nodes outside the view must still show
if you pan or zoom out. (b) contradicts a decision already made, so it
is not a free choice between two readings.

**Two causes, both measured** at 1879×622, preset MediumFast:

| fit set | zoom | result |
|---|---|---|
| all 401 positioned | 6 | 6 < 7, no fit ran — map stayed at the configured view |
| the 400 inside Arizona | 7 | the fit runs and centres on the mesh |

One node near Oakland decided the opening view for the whole mesh.
#114 stopped a far node zooming the map *out*; it did not stop one
**cancelling the zoom in**.

The second cause is that a centre plus an **integer** zoom shows a
different area on every screen shape. At that box, zoom 7 shows about
20° of longitude and Arizona — about 6° wide — filled under a third of
it. `zoomSnap: 0.25` lets `fitBounds` land where it means.

**The home region is four settings, not a constant.** Arizona by
default because this deployment is Arizona's; another mesh sets four
numbers and `app.js` does not change. A test asserts those four numbers
appear **nowhere** in the JavaScript, because a hardcoded box would
pass every other check here and be wrong for everyone else.

**The filter applies to the vote, not to the map.** Nodes outside the
region are still drawn and still reached by panning. A test reads the
drawing step and asserts it does not use the filtered set — because the
failure mode of getting that wrong is exactly reading (b), which was
rejected.

**A #114 guard went red and was repaired, not relaxed.** It required
the literal `CONFIG.mapZoom` within 1,200 characters of the fit. #195
makes the floor the home *region*, which is stricter — a box rather
than an integer — and the explanation pushed the fallback past the
window. The test now sizes its window to the block and asserts the
property (a floor exists; a widening fit is refused) rather than one
spelling. Proven still sharp by mutation: removing the refusal turns it
red. This is the second test in this session broken by a comment
growing past a fixed character window; a window measured against a
literal length is a fragile instrument.

### The message item and the live map dots (#199, #196)

Built to the proposals posted on both issues, after Will delegated the
design calls.

**URLs in a message body stay text, never links (#199).** 21 of the
latest 50 messages carry one. A message body is text anyone on the mesh
can send and nothing checks who sent it, so a clickable link would put
an unchecked destination on the project's own page wearing the
project's credibility — the #81 shape in a new place. Shortening needs
**none** of a link's mitigations: no scheme allowlist, no `rel`, no
question about a message dressing a link as something else. The full
URL stays on the element for anyone who wants it.

The test for this mutates the *plausible* future edit — "why isn't this
clickable?" — into an `<a href>`, not an obviously broken one.

**No clustering on the map (#196).** A cluster replaces a position with
a count drawn at a centroid, and these positions are already fuzzed to
between 1.4 km and 5 km (#96). A centroid of uncertain coordinates
invents a place. The blob at least tells the truth about density, so
the fix is marks that fit the zoom.

**The gateway ring waits for zoom 9.** Sampled in light mode, the most
common opaque colour on the whole map was the gateway stroke: 80 rings
were more of the visible ink than any role colour, which inverts what
the map is about. A gateway is not a role and the ring must not take
the colour over.

**Automated senders keep everything but their loudness.** The reporter
decided they all stay — no filter, no folding. Only the body colour
softens, and a test asserts nothing drops a message for being
automated, because that is the change this must not become.

**Three tests were repaired, none weakened**, and all three broke the
same way: **a fixed character window around a rule, overrun by a
comment.**

| test | window | what it now does |
|---|---|---|
| halo never paints over a dot | literal `radius: ... ? 7 : 5` | computes the widest possible dot edge from the radius scale and compares it with the hole |
| watch control styling | 400 chars of raw CSS | reads the rule to its closing brace, comments stripped |
| (earlier, #195) opening view | 1,200 chars | sized to the block, asserts the property |

The halo repair is strictly stronger than what it replaced: it caught a
mutation from 6.5 px to 12 px, which the literal string match could not
have seen. The invariant itself never moved — the widest gateway edge is
8.25 px both before and after, being 7 + 2.5/2 and 7.5 + 1.5/2.

**A window measured in characters is a fragile instrument**, and this
is now the third and fourth instance in one session. The pattern to
prefer: find the construct's own boundary, and strip comments first.

### The Config check page's layout and vocabulary (#202)

**`warn` and `info` keep words of their own.** The obvious move was to
reuse the health checklist's Good / Needs fixing / Can't tell yet
(#95), and two of the three map cleanly. The third does not: "Can't
tell yet" means the evidence is missing, while `warn` and `info` mean
"we looked, and it is worth your attention" — which is what the score
row already calls **Worth a look**. Making two pages match by having
one of them say something slightly untrue is the wrong trade.

**The vendored checker is not edited.** The emoji come from its `icon:`
field; the sprite mapping lives in `config-check.js`, so
`PROVENANCE.md` and `check_config_checker_pin.sh` stay intact and
nothing has to be redone on an upstream update.

**An early draft of that mapping referenced icons that do not exist** —
`i-radio`, `i-device`, `i-shield`, `i-check`. A `<use href="#i-nope">`
renders **nothing**: it does not throw and does not warn, so it looks
like a styling problem rather than a typo, and every other test would
have passed. There is now a control asserting every icon name the page
uses is a real symbol in `index.html`, proven by mutation.

**The Optional panel and the downloads moved in the DOM, not in CSS.**
`order:` on a flex container would have moved them visually and left a
keyboard user tabbing through the old sequence, which fails WCAG 2.4.3.
A test asserts the ordering is structural, and the HTML was parsed to
confirm the move left no unbalanced tag.

### #193 items 3 and 6, and two defects the first attempt had shipped

**Health sits under Device, inside the summary row.** Device is short
and Activity sets the row's height, so there was empty space under
Device while Health ran as a full-width strip below. Measured on the
running page after the change: Health at **y=320**, against **y=631**
before — #95's first-screen requirement is not merely preserved, it is
better, because Health now starts where Device ends rather than where
the whole row ends.

**`#map/node/<id>?preset=...` opens the map on one node.** The preset
travels in the fragment because the map draws one preset at a time
(9.7); without it a node on any other preset is not drawn and the link
lands on empty ground.

**I wrote that comment and then did not implement it.**
`mapFocus.preset` was stored and never read. The trap the issue warned
about was live in my own code, behind an explanation of why it must not
be. Verified afterwards on the running page: following `?preset=Weather`
selects Weather, not the MediumFast default. There is now a test that
the preset is read where the channel is chosen.

**The focus mark is a style, not a popup.** A popup was the obvious
choice and does not survive: the live map polls, `drawMapNodes` clears
the layer, and the popup goes with it — measured, already closed six
seconds after following the link. The mark is recomputed inside
`nodeStyle`, so it is reapplied on every redraw and zoom change, and it
is a width *and* a hue so it survives a greyscale render.

Later (#264): the clearing itself was the bug for every reader, not just
for a focus link. A bubble the reader opened by clicking also closed on
the next Live refresh. `drawMapNodes` now keeps one marker per node id
and updates it in place, so a popup survives a refresh; the focus mark
stays a style because it needs no click to dismiss and hides nothing.

### The part that matters most: #193 items 1 and 2 were not fixed by #207

I claimed them from reading the CSS. Measuring the rendered page found
both still broken:

| | claimed in #207 | actually measured |
|---|---|---|
| left edges | one | **413 and 494** |
| widths | one | **1600 and 1438** |
| gaps | uniform | **32, 16** |

`.grid` carries `margin-inline: auto`, and an auto inline margin in a
flex column makes an item **shrink-to-fit instead of stretch** — so the
summary row sized to its content and centred, which is exactly the
mismatched left edge the issue reported.

Then the fix failed **twice more**, both times looking correct in the
stylesheet:

1. `[data-node-body] > *` — one attribute selector, loses to two classes
2. `[data-node-body] > .grid` — ties on specificity and **loses on
   source order**, because `.grid.summary-row` is defined later

Three attempts, two silent no-ops, caught only by re-measuring each
time. Final state, measured: one left edge (413), one width (1600),
gaps 16 and 16.

**The lesson is not about CSS.** A layout claim read off a stylesheet is
a prediction; the rendered page is the observation. `docs/DECISIONS.md`
already says "done means measured on the running thing" — this is the
first time in this session that rule caught *me* having shipped
something.

**A sixth comment-vs-code false result**, in the same stretch: adding a
comment that named `.grid.summary-row` made an existing test's
`CSS.index(".grid.summary-row")` find the prose instead of the rule.
Both affected tests now strip comments before indexing.

### The Config check report view, and the cause of the five widths (#202.1, #202.3)

**Measured on the rendered page, before and after:**

| | before | after |
|---|---|---|
| where the report starts | ~660 px | **258 px** |
| left edges | 5 widths, capped rows 141 px inset | **one (272)** |
| widths | 1881 / 1600 / 683 / 523 / 388 | **one (1136)** |
| gaps | uneven | **16 / 16 / 16** |

**The five widths were not a CSS problem.** `.page-head` — a wrapping
flex row with `justify-content: space-between` — wrapped **all nine** of
the page's blocks, so every one was a flex item sizing to its own
content. No amount of capping fixes that. `page-head` now closes after
the title and the rest are siblings.

I found it only by asking the rendered page what the section's children
were, and getting **one**.

**Three further things that looked right and did nothing**, each caught
by re-measuring:

1. `[data-page="config"] { display: flex }` — loses to `.page.active`,
   which is two classes. The column simply never applied. (It also
   means the feared side effect — the config section showing on every
   page — never existed.)
2. `margin-block: 0` — beaten by **inline** `style="margin-top:1rem"` on
   two blocks. An inline style beats every selector.
3. The browser served a cached `index.html`, so the restructure appeared
   not to work. Disk and served bytes had to be compared to tell a stale
   cache from a broken edit.

**`state.fileName`, not `state.filename`.** My first draft read a field
that does not exist, so the strip would have said "Checking a config"
for every file ever loaded — a fallback quietly doing the work of a
bug. A test now forbids the wrong spelling.

**The standing lesson, now earned four separate times in one session:**
a layout claim read off a stylesheet is a prediction. Only the rendered
page is an observation. Every one of the failures above was invisible in
the source and obvious in the measurement.

### The backup offered before a USB write could not restore a node (#117)

**A correction, and the second one this feature has needed after real
hardware met it.**

The page offers "Download a backup of the current config first", ticked
by default, directly above a control that writes to somebody's radio.
The file it produced restored nothing. `ConfigFixer.exportFixed` writes
a DeviceProfile — top-level `device:`, `lora:`, `module:` — and
`meshtastic --configure` reads only `config:`, `module_config:`,
`owner` and `channel_url`. The download worked, the YAML parsed, and
the restore was a no-op. It also dropped the channels, keys, bandwidth,
spreadFactor and txPower, wrote literal `undefined`, and named
`--import-config`, which is not a CLI flag.

**A backup that silently restores nothing is worse than no backup.**
The tick box is what makes the write feel safe enough to attempt, so a
file that cannot restore actively buys the risk it claims to cover.

`config-backup.js` writes what the CLI reads, from what the USB read
actually returned, and **refuses** rather than producing a file that
would not work. A refusal now stops the write, because proceeding as
though a backup had been taken is the dishonest half of the original
bug.

**An empty section is never written.** The CLI reads a present-but-empty
section as "set this to nothing", which is the same shape as the
whole-section bug #201 fixed.

**The tests run under node**, because the thing under test is a *file
format*: whether these bytes are bytes the CLI consumes. Every
source-level check the old exporter had, it passed.

### And the verification lesson, which is the real cost

I described the USB write as "verified against real Meshtastic firmware
2.7.26" repeatedly, including in the handoff written on #115 for
whoever ran the hardware test. That description was wrong.

The meshtasticd run re-read **the field it had changed and the fields it
had explicitly protected**. Both are fields somebody was already
thinking about. It never re-read the rest of the section — and the bug
lived exactly there, in the fields nobody was thinking about, which is
the only place a bug of that shape can live.

This sits directly beside the entry above it about the bare
`AdminMessage`, where running against real firmware *caught* what a
simulator missed. Both are true, and together they say something
sharper than either alone: **running against the real thing is
necessary and not sufficient. What you re-read afterwards decides what
you can claim.**

> After a write, re-read the whole section and diff it. Never just the
> field you changed.

### Board membership is a live value, not a remembered one (#178 family)

**Corrected 2026-09-24.** The working belief for most of this session
was that **#178 was the only issue on the Roadmap board**, so its three
children were ungated and fair game. I said so more than once.

Checked directly, four are on it and **all four are `Ideation`**:

    #178  Ideation   Noise Floor Tracking
    #179  Ideation   Sonoran-Contributor docker service
    #181  Ideation   Sonoran - Contributor management
    #182  Ideation   Sonoran - Noise Floor display

`Ideation` is not `Ready`, so under Tyler's rule none of them may be
started. Nothing was: no branch or PR references any of the three. The
only thing that reached them was a comment on #182 about a naming
collision, which is not starting work.

**The fact was true when it was learned and false when it was used.**
#178 really was the only one on the board when that was reported; the
other three were filed afterwards. Repeating it later was not repeating
a fact, it was repeating a *reading*.

This is the same shape as everything else in this file — a gate result
is a claim about a **moment** — and it is the more dangerous version,
because the claim was accurate at the time and nothing about it looked
stale. The fix is not to remember harder. It is that **membership is
cheap to re-ask and must be re-asked**, which `AGENTS.md` 9.28 now
requires with the query to do it.

**And the instrument mattered.** Earlier in this session an empty
`projectItems` was read as "not on a project". That call returns a bare
`[]` when the token lacks the `project` scope — no error. The GraphQL
form errors loudly instead, which is why 9.28 specifies it. An empty
result and a true negative are the same bytes until the instrument is
proven.

**It is worse than an unreliable command, because it survives being
tested.** The call is truthful on a machine with the scope and silent on
one without, and nothing in its output distinguishes them. So checking
it *confirms* it — on the host where it happens to work — and that
confirmation then travels to a host where it does not. A passing test is
no evidence at all here: the failing case is indistinguishable from
inside the passing one. This is the sharpest form of a false green in
this file, and it was named by the peer session that found the stale
board reading, correcting its own first framing to get there.

**Credit where it is due:** this came from a peer session that had the
scope to look, checked before telling me, and named its own part in
propagating the stale reading rather than just reporting the fix.
