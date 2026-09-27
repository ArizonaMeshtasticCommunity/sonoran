# UX overhaul — plan

Will's brief, 2026-09-26, worked through so nothing in it is lost. Every
item below is his unless marked **[found]**, which means it turned up
while checking his items and he has not seen it yet.

The bar he set, which applies to every item: secure, fast, easy to use,
current in its design, correct on a phone and a tablet as well as a
desktop, and free of bugs. That is not decoration on this document — the
items most likely to fail it are named in **Risks** under each one.

Nothing here is started. **Four decisions are Will's** and are collected
in §2; three of them change what gets built, so they come before code.

---

## 1. Ordering, and why

Five phases. The order is not the order Will wrote them in; it is what
has to exist before what.

| Phase | Why it is here |
|---|---|
| **A. Foundations** | Settings store, units, tooltips, table pattern, icons. Nine later items are one of these five things applied to a page. Building them per page is how five tooltip styles happen. |
| **B. Corrections** | Auto-ack rules, copy removals, padding, label wording. Small, independent, each one shippable alone. Early because they are the ones a reader notices daily. |
| **C. Tables** | Firehose, Traceroutes, Chat table, Nodes. Depends on A's table pattern. |
| **D. Page rebuilds** | Chat as a real chat, Nodes list, Weekly check-in, Map and Graph headers, Planner simple/advanced. The large ones. |
| **E. Links between pages** | Dashboard chart → filtered Firehose. Last because it depends on the Firehose knowing how to be filtered by URL. |

A phase does not have to finish before the next starts, but an item does
have to wait for the foundation it uses.

---

## 2. Decisions for Will

These change what gets built. Each has a recommendation.

### 2.1 Auto-ack: three marks your list leaves out

You wrote: *"Auto-acks are always 1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣*️⃣ and anything else
isn't an auto-ack."*

The code today also treats **`#`**, **`0`** and **🎯** as auto-acks, and
not arbitrarily — `app.js` cites `docs/features/automation-engine.md` in
Yeraze/meshmonitor: `*` means a direct hit, `1`–`7` the hop count, `#`
means it arrived over MQTT, and older builds sent `0` or 🎯 for direct.

If we follow your list exactly, an MQTT-delivered ack and an ack from an
older node stop being delivery signals and get drawn as reactions people
chose.

- ~~(a) Keep `#`, `0` and 🎯 as auto-acks~~
- **(b) DECIDED, 2026-09-26: follow the list exactly** — only `1`–`7`
  and `*`.
- ~~(c) Keep them but label them separately~~

**The consequence, recorded so it is not later read as a bug.** An ack
that arrived over MQTT (`#`) and an ack from an older node (`0`, 🎯) will
now be drawn as reactions a person chose, because nothing in the packet
distinguishes them. This is a deliberate choice in favour of matching what
the operators see on their own radios, and the code comment must say so
and cite this decision -- otherwise the next person will "fix" it back.

### 2.2 "Auto-acked" without the hedge

You asked for *"Possibly auto-acked"* → *"Auto-acked"*. Once the channel
rule lands the hedge is mostly unnecessary, and this is why it existed:
nothing in the packet distinguishes a person sending 3️⃣ from a node
sending it. On MediumFast, LongFast and azmsh that is now a safe bet.

- **(a) "Auto-acked" on the three channels, chip hidden elsewhere**
  *(recommended)* — matches your rule exactly, no hedge where we are
  confident and no claim where we are not.
- **(b) "Auto-acked" everywhere** — simpler, and wrong in Trivia.

### 2.3 Cookies or `localStorage` for the settings page

You said cookie-based. `localStorage` is the better mechanism here and we
already use it for the preset:

- a cookie is sent on **every** request, including every tile and asset,
  so a settings cookie is bytes on the wire thousands of times a session;
- the server does not need to know. Units convert in the browser (§3.2),
  so nothing server-side reads the value;
- it is the same store the preset switch already uses, so one mechanism
  rather than two.

A cookie would only be needed if the server had to render units itself.

- **(a) DECIDED, 2026-09-26: `localStorage`.** One mechanism for the
  preset and the settings, nothing on the wire, and the same wrapping
  `preset.js` already proved against a private window.
- ~~(b) Cookies~~

### 2.4 Radio climate from the location — we cannot do this properly

You asked whether Phoenix vs Flagstaff can be determined. Checked:
`coverage/params.py` holds five ITM climate codes with `desert` as the
default, and there is **no dataset in this repo that maps a coordinate to
a climate**. ITM's codes are coarse (equatorial, continental subtropical,
maritime, desert, continental temperate) and the choice changes the
prediction.

Options, none of them free:

- **(a) DECIDED, 2026-09-26 (revised the same day): `desert` in Simple,
  choosable in Advanced, and the lookup filed as its own issue — #239.**
- ~~(b) Derive it from elevation~~
- ~~(c) Ship a climate lookup~~ — chosen, then reversed once costed. The
  costing is kept below because it is the useful part and the next person
  should not have to redo it.

**What the separate issue has to carry.** A lookup is not a UI change. The
five codes the engine takes are ITM's: equatorial, continental
subtropical, maritime subtropical, desert, continental temperate.
Answering "which of these five, for this coordinate" well enough to
improve a prediction means:

1. choosing a **Köppen-Geiger** dataset — the standard source, published
   as a raster — and checking its licence permits redistribution;
2. writing the Köppen → ITM mapping and documenting each decision, since
   that is where the judgement is and it must be reviewable;
3. picking a resolution. Arizona spans desert (Phoenix, BWh) and
   continental temperate (Flagstaff, Dsb) within 200 km, so a coarse grid
   defeats the purpose;
4. deciding what ships. A world raster is megabytes; cropping to this
   region is smaller and honest, but a site outside the crop must then
   fall back rather than answer wrongly;
5. serving it. `src/sonoran/terrain/` is the precedent for shipping
   geographic data and the obvious home.

**The risk that made it its own issue.** A lookup that is confidently
wrong is worse than a default that is openly a default, because the reader
has no reason to check it.

**Until then:** Simple uses `desert` and does not hide that it is a
choice — a beginner in Flagstaff is the case it is wrong for, so Advanced
stays the answer.

---

## 3. Phase A — foundations

### 3.1 A settings page, and a `settings.js` store

**What.** A new page at `#settings`, a nav link at the bottom, and a
store like `preset.js`: read, write, subscribe, validate, and survive
storage that throws.

**Settings it holds.** Units (imperial/metric), temperature (°F/°C),
appearance (system/light/dark, moved off the menu button).

**Approach.** `preset.js` is the working precedent, including the part
that matters: a stored value is only honoured when it is still valid, so
a hand-edited or stale value cannot wedge the site. Every read and write
wrapped, because in a private window both throw.

**Menu footer becomes**, per Will:

    Preset   [ Medium Fast | Long Fast ]      <- sliding switch, §3.5
    Settings                                  <- link
    ● Connected · Updated 11:11               <- status

**Risks.** The appearance control moving to a settings page costs a tap
for something people do change. Keeping the cycle button in the menu *and*
a control in settings means two controls for one value, which is the drift
this project keeps paying for. Recommend: settings page owns it, and the
menu keeps a small current-state indicator only.

**Tests.** Defaults; a stale value ignored; storage that throws; each
consumer re-rendering on change; the nav link last.

**Done when** a reader can set units, temperature and appearance, reload,
and find them kept.

### 3.2 Miles and feet

**What.** Every distance and height in the interface reads in miles and
feet when imperial is chosen. Temperature follows the same setting.

**Approach — convert at display, never in the API.** The API keeps SI and
keeps saying so: `distance_km`, `"unit": "km"`. One formatter,
`format.js`, owns every conversion and every rounding rule. The
alternative — an API that returns whichever unit the caller asked for —
puts a display preference into the data layer and makes every cached
response unit-dependent.

**Scale, measured.** `km`/`metres` appear in six frontend files
(`app.js`, `rf.js`, `planner.js`, `coverage.js`, `gaps.js`, `siting.js`)
plus `planner-params.js`, and the API emits `distance_km` and
`"unit": "km"` in leaderboards and the node page. This is the widest item
in the brief.

**Risks.**

- **The planner must not be converted twice.** It takes heights in metres
  and the engine takes feet, and `planner-params.js` already converts.
  That conversion is internal and must stay in metres; only the *label*
  and the *typed value* change. `docs/PLANNER.md` records that getting
  this wrong overstates every antenna by 3.28×.
- **Rounding changes meaning.** "0.3 km" becoming "0.2 miles" is fine;
  "12 m mast" becoming "39.37 ft" is not — masts are whole feet.
  Per-quantity rounding, not one global rule.
- **[found] The RF page uses metres for spectrum work**, where metric is
  the convention of the field. Converting those may be wrong. Needs a
  look before it is swept in.

**Tests.** A table of known pairs per quantity; the planner's
metres→feet path unchanged under both settings; no API response altered.

### 3.3 One tooltip pattern

**What.** An info icon with a tooltip, used for: every leaderboard title
(§4.1), every table column header (§5.1), and the Nodes columns (§6.2).

**Approach.** One component. Must work by tap as well as hover — a
hover-only tooltip is invisible on a phone, and this is going on the
pages most used on phones. `<details>`/`<summary>` is already the pattern
for reaction senders (#44) and needs no hover and no JavaScript.

**Risks.** Tooltips in table headers on a 320 px screen will overflow the
cell. The pattern has to be chosen for the narrow case first.

**[found] Accessibility.** `title` attributes are not reachable by
keyboard and are skipped by some screen readers. The site already holds
itself to naming controls properly (`test_ui_readability.py`), so the
component needs a real accessible name, not a `title`.

### 3.4 One table pattern

**What.** Firehose, Traceroutes, Chat table, Nodes and every other table:
no per-row "open" link; the whole row clickable; time first and visibly
clickable; tooltips on column headers.

**Approach.** A shared row renderer. Time in the first column, styled as
the affordance.

**Risks, and this one is real.**

- **A clickable row cannot contain links.** Several of these rows already
  hold a node link and a packet link. Nesting an anchor inside a
  clickable row breaks both keyboard and middle-click. The pattern has to
  be: the row's *first cell* is the link, and inner links stop
  propagation.
- **Keyboard and screen readers.** A `<tr>` with an `onclick` is not
  reachable by Tab and announces nothing. The time cell should be a real
  link or button so the row is operable without a mouse.
- **[found] Losing "open" loses the URL.** Those links are how somebody
  copies a link to a packet. If the row becomes a click handler with no
  `href`, right-click → copy link stops working. The first cell must be a
  real `<a href>`.

**Tests.** Every table has a first-column link; no row has a nested
anchor inside the row-level handler; keyboard reaches every row; the
existing packet and node links still work.

### 3.5 Icons on buttons, and the preset switch

**What.** Icons beside button text where it helps (Share on the planner
was Will's example). The preset control becomes a sliding switch.

**Approach.** Audit every button, add an icon only where the icon is
unambiguous. Existing sprite first; a `<use>` pointing at a missing
symbol renders **nothing, silently** — three bugs in this repo have been
exactly that, so every new icon needs a test that its symbol exists.

**Risks.** Icons on everything is noise. Recommend: destructive, sharing,
and export actions get one; ordinary filters do not.

---

## 4. Phase B — corrections

### 4.1 Leaderboards: info icon instead of "What this cannot know"

`app.js:1264` renders a `<details>` per board. Replace with the §3.3
tooltip on the title. The text itself is kept — it is the honest part of a
ranking — and moves into the tooltip.

**Risk.** A tooltip is less visible than an open disclosure. These
caveats are the difference between a leaderboard and a scoreboard, so the
icon must be obviously interactive, not decorative.

### 4.2 Auto-ack rules — SHIPPED 2026-09-26

**What.** Auto-ack marks only count on **MediumFast, LongFast, azmsh**.
In Trivia, 1️⃣–4️⃣ are people answering questions. Label becomes
"Auto-acked".

**Approach.** `reactionChips(reactions)` **has no channel argument today**
— the rule cannot be applied without threading the channel through, so
that is the first change. The channel list already marks presets
server-side (`group: "Presets"`), and azmsh is `tier: core`, so the rule
can be expressed against data rather than a hardcoded list of three
names. Recommend deriving it: presets plus core channels.

**Risks.** Getting this wrong in the other direction is worse than today:
a human reaction relabelled "Auto-acked" with no hedge is a confident
false statement. Trivia is the test case and belongs in the tests.

**Tests.** 3️⃣ in MediumFast → auto-ack. 3️⃣ in Trivia → a reaction. 👍 in
MediumFast → a reaction. Whichever of §2.1 Will picks, asserted per mark.

### 4.3 Copy and padding

- **SHIPPED 2026-09-26. Config checker:** remove the "Node plugged in by
  USB?…" paragraph.
  **[found]** `#115`'s "Done when" includes removing the cfgtest link,
  and this paragraph is that link. Removing it here partly satisfies an
  open issue — worth saying on #115 rather than silently.
- **Config checker:** padding between the widgets on desktop. Same cause
  as the gaps page had: `.page.active` is `display: block` and `.panel`
  carries no margin. Same fix, and the same trap — `width: 100%` on the
  children, because `.grid`'s `margin-inline: auto` makes a flex item
  shrink-to-fit (#193.1).
- **SHIPPED 2026-09-26. Live map:** "Packet kinds" → "Packet Types",
  "Other kinds" → "Other Types", "All kinds" → "All Types". Three further
  sentences said "kinds" about packets and were changed with them.
- **SHIPPED 2026-09-26. Live map:** remove "Every preset, any time". **[found]** This is the
  override that shows every preset at once; with the global selector it is
  the last per-page preset control on the site, so removing it is
  consistent — but it is also the only way to see the whole mesh on one
  map. Flagging rather than assuming.
- **SHIPPED 2026-09-26. Graph:** remove the "Open mesh-graph" link. It was
  the last use of `CONFIG.graphBaseUrl` in the browser; the SETTING stays,
  because it feeds the CSP and the server builds the node page's link from
  it.
- **Chat:** remove the caption. Quoted in the brief as "The newest 100
  messages in the window, newest first."; the actual string is a template,
  `app.js:5853`: ``The newest ${count(messages.length)} messages in the
  window, newest first.`` Named exactly because the count in it is the
  number Will wants moved beside the channel title, so the string is not
  simply deleted -- the number moves.

---

## 5. Phase C — tables

### 5.1 Firehose, Traceroutes, Chat table

Apply §3.4. Then:

- **Traceroutes:** drop the drawings column and the packet-number column.
  **[found]** Check first whether anything links to a traceroute *by*
  packet number — `app.js` has a `by-packet` route — because dropping the
  column is fine but dropping the ability to find one that way is not.
- **Firehose:** must accept a type filter and a window in the URL, for
  §7.1 to link into it. Show the window ("24 h") in the header.

---

## 6. Phase D — page rebuilds

### 6.1 Chat as a real chat

**What.** Newest at the bottom, oldest at the top, scroll up to load
more, header pinned, full height, and a date/time range instead of
24 h / 7 d / 30 d. The table view keeps newest-first.

**Feasible:** `api/chat` already takes `since` and `before`, so both the
range picker and upward paging work without new endpoints.

**Risks — this is the hardest item in the brief.**

- **Scroll anchoring.** Prepending older messages moves the viewport
  unless the scroll offset is corrected in the same frame. Done wrong,
  the list jumps every time it loads.
- **Live + pinned-to-bottom fight each other.** A new message must not
  yank the view while somebody is reading history. The rule needs to be:
  stick to the bottom only when already at the bottom.
- **A date range can select a million messages.** The window has to stay
  paged, and the empty state has to distinguish "nothing in this range"
  from "still loading".
- **[found] Two views, one URL.** The view already lives in the fragment.
  A range has to go in the fragment too or a shared link loses it.

### 6.2 Nodes page

- Move "Start from / Silent routers / No position / Gateways / Newest
  first / Clear" into the Filters panel as **Filter Presets**.
- Fix the info icon causing a line break.
- Sort indicator: a neutral up/down glyph that becomes the orange arrow
  when active. Header becomes **Name · info · sort**.
- Replace "569 nodes · showing 300" with infinite scroll. The API already
  takes `limit`/`offset`.
- Drop "· sorted by name · 2 filters": the column shows the sort, and the
  Filters button carries a count and an active state.
- **The search button:** yes, remove it. The box already debounces
  (`NODE_SEARCH_PAUSE_MS`). **[found]** The button is also the Enter
  affordance, so Enter must keep working and the box needs a visible
  "searching" state, or removing it will read as a regression.
- More filters: everything sortable becomes filterable.
- Hardware filter: **57 models**, 17 of them with ≤2 nodes. Top 10 plus
  a search box plus "show more" — Will's suggestion, and the numbers
  support it.

**Risks.** Infinite scroll plus a live-updating list can duplicate or skip
rows as the underlying order shifts. Keyset pagination on a stable sort
key, not `offset`, or rows will repeat. **[found]** Infinite scroll also
breaks "jump to the end" and browser restore-scroll; a "load more" button
as well as auto-load is the usual answer.

**Infinite scroll, more filters and the hardware picker — SHIPPED
2026-09-26.** With three things this plan should record rather than let
the next reader discover.

**It pages on `offset`, not on a keyset.** `/api/nodes` serves
`limit`/`offset` and has no keyset cursor, and adding one is a change to
a documented endpoint that something outside this repository may read —
for a page whose rows shift only between one reader's own scroll events,
because nothing on this page refreshes on a timer. So the risk above is
answered rather than avoided: `mergeNodePage` drops a row whose
`node_id` is already on screen, so the repeat this section warns about
cannot be drawn. **The other half is not solved and cannot be from the
browser**: a row that moves FORWARD a page between two requests is
skipped, and nothing can see that it was. If this list ever gains a live
timer, that becomes a real hole and the keyset is the answer.

**"More filters" was nearly already true.** Every sortable column could
be narrowed except one, and that one only in a single direction:
`active_hours` asked "heard since" and nothing asked "not heard since".
`quiet_hours` was added to the API for it. The contract is now held by a
test that reads `SORTS` out of `routes/nodes.py` and checks each column
against the panel, so the claim cannot rot into a list. The search box is
deliberately not duplicated into the panel: `q` already covers name and
node ID, and two controls doing one job is what this page was corrected
for.

**The "searching" state asked for above was not needed, and the item that
removed the button already shipped without it.** Recorded here because
the sentence is still in the list above: the box debounces at 350 ms and
the table is replaced with "Loading" on the next keystroke pause, so
there is a visible state; it is the table, not the box.

### 6.3 Weekly check-in, with streaks

**What.** Which nodes checked in, a streak count beside the name,
highlight a missed check-in or a broken streak, and rethink the page.

**Approach.** The data is tagged messages (`api/chat/tagged?tag=meshnet`).
A streak is consecutive weeks with at least one tagged message, computed
server-side — it is a windowed aggregate over weeks and does not belong
in the browser.

**Risks.** "Missed a check-in" is a claim about somebody's
participation, and getting it wrong is worse here than on any other page
in the brief, because it is about people rather than radios. A node that
was off, or whose message did not store, must read as "no message found",
not "missed". **[found]** Message text storage can be off entirely
(`docs`), in which case this page has nothing to compute from and must
say so rather than show everybody at zero.

### 6.4 Map and Graph headers on one row

**What.** Title, subtitle and controls on a single row; clean; current.

**Risks.** This is the item most likely to break the phone layout, which
is the one the brief says must be right. A row that fits 1440 px wraps at
390 px, so it needs a deliberate narrow-screen shape — not the wide one
squeezed. The map already has a documented tight-height mode
(`max-height: 32rem`).

### 6.5 Planner: simple vs advanced

**Simple** is for somebody who just got their first node.

Moves to advanced: Frequency, Sensitivity, gain typed by hand, radio
power typed by hand, cable loss typed by hand, and all of Ground and air.

Simple defaults: MediumFast on **slot 18**; ground and air fixed at
`desert` (§2.4). **This item waits on nothing** -- the climate lookup is a
separate issue and Phase D proceeds without it.

Advanced: preset, slot and frequency **linked** — changing one updates
the others.

Plus: address/city search for the site; the map centred on Arizona rather
than the United States; less space between the subtitle and the tool;
`"I'll type the…"` options no longer truncated.

**Risks.**

- **Geocoding is blocked by our own CSP.** `connect-src 'self'` — a
  third-party geocoder cannot be called from the page. It needs a
  server-side proxy endpoint, which also keeps the reader's typed address
  off a third party. That is a new endpoint with rate limiting and input
  validation, and it is the only item in this brief with a security
  surface. Treat it as its own piece of work.
- **Preset/slot/frequency linkage is a three-way binding.** Each can be
  edited; a naive implementation loops. One direction of truth per edit,
  and it must not fight the share link.
- **Hiding sensitivity is not the same as ignoring it.** It still has to
  move with the preset, or a simple prediction is wrong by up to 13 dB.
  `test_planner_documented_defaults.py` already guards that pairing.

---

## 7. Phase E — links between pages

### 7.1 Dashboard chart → filtered Firehose

Clicking a packet type opens the Firehose filtered to it, over the same
24 hours, with the window shown there. Needs §5.1's URL filter.

**Risk.** The chart is ECharts; its click events give a series index, not
a portnum. The mapping has to be explicit or the wrong filter opens —
silently, because a valid-looking filter with no rows looks like a quiet
mesh.

---

## 8. Other settings worth having

Will asked. In the order we would add them:

1. **Time format** — 12 h or 24 h, and absolute or relative ("11:11" vs
   "3 min ago"). Timestamps are everywhere in these tables.
2. **Live updates off by default** — some pages poll every 15 s. A reader
   on a phone hotspot may want it off site-wide, not per page.
3. **Reduced motion** — the live map animates. The OS already exposes
   `prefers-reduced-motion`; this would let somebody override it here.
4. **Default landing page** — somebody who lives on the Nodes list should
   be able to open there.
5. **Node identity** — show long names, short names, or IDs. The three
   appear inconsistently across pages today.
6. **Table density** — comfortable or compact, which matters on a tablet.
7. **[not recommended] A units-per-quantity setting.** Tempting, and it
   is how you get altitude in feet and distance in kilometres on the same
   screen.

---

## 9. What this brief does not cover, and should

**[found]**, all of it:

1. **The `#232` overlap.** Tyler asked for exactly this kind of global
   control, and also for *dimming filters that do not apply to the page*
   and *highlighting active ones*. Item §6.2's "Filters button shows a
   count and an active state" is a piece of his point three. The two
   should be designed together, not twice.
2. **`#233`, node graph scrolling**, is open and touches §6.4.
3. **Performance has no number in this brief.** "Super fast" cannot be
   tested. Recommend a budget per page before Phase D: time to first
   render, and rows rendered per frame on the long tables.
4. **Nothing here says what happens on a slow connection.** Infinite
   scroll, a date range over a month, and a settings page all behave
   differently at 3G. The empty and loading states are part of each item,
   not a pass at the end.
5. **No accessibility pass is named.** Clickable rows, tooltips and a
   sliding switch are the three patterns most often built mouse-only.
   `test_ui_readability.py` exists and should grow with each phase.
6. **The RF page is absent from the brief** but has tables and metres,
   so §3.2 and §3.4 reach it whether or not that was intended.

---

## 10. How each item gets reviewed

Per item, before it is called done:

1. **Unit tests**, including the failing state. A check only ever seen
   passing is not evidence it can fail.
2. **Mutation check** on anything that guards a visible behaviour, with
   the mutation confirmed to have landed before the red is trusted.
3. **Measured on the running thing**, not read off the diff. This session
   alone has produced a config-zeroing bug, a monitor that reported
   success while checking nothing, and a watch bar that would have named
   the wrong preset — none of which a diff showed.
4. **Three widths**: 390 px, 834 px, 1440 px. The brief asks for phone,
   tablet and desktop, so a desktop screenshot is not a pass.
5. **Both themes**, since two of these items are colour changes.
6. **Keyboard only**, for anything that gained a click target.

**A gap worth knowing before Phase D.** Nothing in this repository catches
an undefined identifier in the frontend. `node --check` parses and does no
scope analysis, and the unit tests read source text -- to them a name that
is merely absent looks the same as a name never used. Removing the live
map's preset override left one `allNodes` reference behind and the map
page threw on every render; the **e2e journeys** caught it, and they
reported 23/23 passing while the console filled with the error, so the
signal is in the console check rather than the journey results.

Phase D removes a lot of controls, so this will happen again. Options:
ESLint with `no-undef` (a new dev dependency and CI time on Logan's
hardware, so Will's call), or accept the e2e as the net and never merge on
a red console. Recorded because the cheap-looking answer -- "run
`node --check`" -- does not work.
