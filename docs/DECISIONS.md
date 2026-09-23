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
