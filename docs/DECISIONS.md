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
