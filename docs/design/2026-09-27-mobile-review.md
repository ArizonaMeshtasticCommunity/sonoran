# Mobile and tablet review (#261)

Will, in #261: *"Overall I think the whole site needs to be reviewed from a
Mobile perspective. There is many things that could use fixing as it relates
to the UI. Research the latest in Mobile UI trends for apps like this and how
we can make the site even better UI."*

This is the review. It changes no code. Each fix it proposes is listed in §5,
sized so it can ship on its own, and is meant to be filed as its own issue.

The short version:

- **The basics hold.** No page scrolls sideways as a whole at 320 px. No form
  control is under 16 px. The drawer menu's links are all 44 px tall.
- **Nothing is sized for fingers on a large touch screen.** Touch sizing
  follows the window width, not the pointer. An iPad in landscape gets the
  desktop sizes, with 69 undersized targets on the dashboard against 10 on a
  phone.
- **Map dots are 5 to 13 px across and have no extra hit area.** That is the
  smallest target on the site, on its most-used page.
- **Three list pages hide most of their table sideways on a phone:** Nodes
  61%, Firehose 64%, Traceroutes 57%. On Nodes, *Last heard* is one of the
  hidden columns.
- **Controls fill much of the first screen on four pages:** Graph, RF, Chat
  and Gaps, at 41–57% on an iPhone 14 and 60–100% on an iPhone SE.
- **Nothing stays put while you scroll.** Once you are 1,200 px down, the menu
  button and the Live toggle are both off-screen. The Firehose is 12 screens
  long.
- **Every page downloads the chart library** (327 kB gzipped of 885 kB), even
  pages with no chart. On a slow 4G profile, content arrives at 5.6–6.3 s.

---

## 1. Method

### 1.1 What was measured, and how

The measurements come from a Playwright 1.49.1 script run against a local
server (`sonoran-api` on :8035, over the shared seeded database, read only).
Every page was loaded cold with its hash in the first `goto`, then given
3.5 s to settle before anything was measured.

| Name used below | Viewport (CSS px) | Engine | Stands in for |
|---|---|---|---|
| iPhone SE | 320 × 568 | WebKit, Playwright `iPhone SE` descriptor | small iPhone, Safari |
| iPhone 14 | 390 × 844 | WebKit, `iPhone 14` descriptor with the full screen height | iPhone, Safari with its bars collapsed |
| iPhone 14 (bars) | 390 × 664 | WebKit, stock `iPhone 14` descriptor | iPhone, Safari with its bars showing (what you see on arrival) |
| Android | 412 × 915 | Chromium, `Pixel 7` descriptor resized | large Android phone, Chrome |
| iPad portrait | 834 × 1112 | WebKit, iPad UA, touch, mobile | 10.5"/11" iPad, Safari |
| iPad landscape | 1112 × 834 | WebKit, iPad UA, touch, mobile | the same, turned |

Both engines report `(hover: none)` and `(pointer: coarse)`, so the site's
touch rules were active.

**The measurements, per page and device:**

- **Header share of the first screen.** This is the top of the first
  data-bearing element (table, panel, map, chart, list) as a share of the
  viewport height. Everything above it is header, title and controls. 100%
  means the first screen held no content at all.
- **Tap targets.** Every visible `a[href]`, `button`, `input`, `select`,
  `summary`, `[role=tab|radio|switch|checkbox]` and focusable element was
  checked.
  - A checkbox or radio inside a `<label>` was measured by its label.
  - A target counts as small if either side is under 44 CSS px (WCAG 2.5.5 AAA
    and Apple's 44 pt). A second count uses 24 px (WCAG 2.5.8 AA).
  - Links inside a sentence are excluded (the WCAG *inline* exception).
  - The off-screen skip link is excluded.
- **Sideways scrollers.** An element counts when `scrollWidth > clientWidth`
  and `overflow-x` is `auto` or `scroll`. The whole document was checked
  separately.
- **Text size.** Every visible text node on the page and in the brand bar was
  measured by its computed `font-size`. The result is the share of characters
  below 16, 14 and 12 px, plus the smallest size found.
- **Controls below the fold.** These are form controls in the page, outside
  tables and feeds, whose top is below the first screen.
- **Hover-only content.**
  - A static scan of every stylesheet rule that has `:hover`, to find any that
    reveals content with no `:focus` twin.
  - A count of `title` attributes, with what each one carries.
  - A read of how Leaflet and ECharts handle a tap.
- **Load time on a phone connection.** Chromium, using CDP network and CPU
  throttling, with the Lighthouse mobile profile ("slow 4G": 150 ms RTT,
  1.6 Mbps down, 4× CPU) and a "fast 4G" profile (60 ms, 9 Mbps, 2× CPU).
  The script recorded first contentful paint, the `load` event, the moment
  the page's first data appeared, and the bytes transferred.

Screenshots were taken of every page on every device and used to read the
numbers. They are not committed.

### 1.2 What emulation cannot show

These questions stay open until someone checks them on a real device. §6
lists them as a checklist.

- **The real address bar.** Playwright's WebKit is not iOS Safari. It has no
  collapsing toolbar, and no iOS 26 floating "compact" tab bar. The two
  iPhone 14 heights bracket the toolbar, but how the page behaves while the
  toolbar animates cannot be measured here.
- **Rubber-band overscroll.** Emulation has no elastic overscroll. The iPad
  top-band report (#253) cannot be reproduced here, and neither can the
  interaction between browser pull-to-refresh and the chat's own scroller.
- **Safe-area insets.** `env(safe-area-inset-*)` read `0px` in both engines.
  The site sets `viewport-fit=cover` and pads from the insets (`app.css`
  §185–188), but whether that padding lands correctly around a notch or the
  home indicator is unverified.
- **Real touch.**
  - Taps were synthesised at exact points, so the "fat finger" error around
    small targets is not measured.
  - Pinch, two-finger map pan and the long-press menu were not tested.
  - Whether a tap on an iPad fires `mouseenter` (which the planner's row
    highlight relies on) is up to iPadOS, not the emulator.
- **Native control rendering.** WebKit on macOS draws a `<select>` as a Mac
  pop-up button, 23 px tall. Chromium draws the same control 44 px tall.
  - Every `select` flagged under 44 px in WebKit is treated as an emulation
    artefact. The Android numbers are used instead.
  - Real iOS Safari renders its own style, so the true height is unverified.
- **Real network, real map tiles.** `MAP_TILE_URL` was empty, so no tile
  images loaded. Real map pages will transfer more and paint later than
  measured.
- **Font rendering, VoiceOver/TalkBack, and the system text-size setting.**
  None of these was tested.
- **The weekly check-in page changed while I was measuring.**
  - The first two runs (SE, iPhone 14) found the "message text is not being
    stored" empty state.
  - Later runs found real check-ins.
  - Its numbers below come from the later re-measurement. Its layout is being
    rebuilt anyway (#262).

---

## 2. Findings across the site

### 2.1 Touch sizing follows width, not pointer

The site enlarges its targets below its phone breakpoints (60rem / 62rem). An
iPad in landscape is 1112 px wide, so it gets the desktop sizes, even though
it matches `(pointer: coarse)` exactly like a phone.

| Target | iPhone 14 | iPad landscape |
|---|---|---|
| Menu links | 44 px tall (drawer) | **38 px** (sidebar) |
| `?` info buttons (`.hint-open`) | 24 × 44 | **24 × 24** |
| Chat sender names (`button.name`) | at least 44 tall | **19 px** tall |
| Preset switch | 174 × 44 | **99 × 34** |
| Undersized targets (<44) on the dashboard | 10 | **69** |
| Undersized targets on chat | 38 | **90** |
| Undersized targets on stats | 11 | **66** |

The CSS already has one rule keyed on `(hover: none)`: the 16 px form-control
rule. The target-size rules have no such rule.

### 2.2 Map dots

- The live map, the node page's map, coverage, gaps, planner and RF all draw
  their markers on Leaflet's canvas renderer (`preferCanvas: true`, `app.js`
  1848).
- The node dot's radius is 2.5 / 3.5 / 5 / 6.5 px, depending on zoom
  (`nodeRadius`, `app.js` 1654). That is a **5 to 13 px** target.
- Leaflet's canvas renderer has `tolerance: 0` by default, and the site does
  not set it, so the hit area is the dot itself.
- tar1090 solves the same problem by raising its hit tolerance from 20 to 30
  (× scale) on mobile (source: `wiedehopf/tar1090` `early.js` / `script.js`).
- Once a dot is hit, the popup is 188 × 137 px with a **24 × 24 close button**.
  Its *Open node detail* action is 126 × 44, which is fine.

### 2.3 Other small targets that matter (iPhone 14 unless stated)

| Target | Size | Where, how many |
|---|---|---|
| Leaflet zoom +/− | 30 × 30 | map, coverage, planner, RF, node page |
| Menu button | 40 × 48 | every page, the only way to navigate |
| Chat timestamps (`a.when`) | 41 × 19 | 22 on chat, 6 on dashboard |
| Chat channel titles / *more* links | 50 × 24, 158 × 32 | chat |
| Chart *Full screen* button | 134 × 30 | dashboard, stats, graph, node |
| Map *Key* summary, *Watch mode* | 57 × 29, 30 × 44 | map |
| Reaction pill (`summary`) | 49 × 24 | chat, dashboard |
| Settings link in the drawer | 37 tall | drawer |

**Row links are not a problem.** Firehose (151), Traceroutes (5) and the node
page's packet timeline (48) have row links only 17 px tall. But
`tr.row-link` makes the whole row the target, and each row is about 60 px, so
they pass under the *equivalent* exception. One side effect: a row also holds
a node-name button, so a tap lands on one of two different destinations
depending on where it falls. Nobody has tested that on a real device.

### 2.4 Tables that scroll sideways on phones

The wrappers are labelled "scrolls sideways" and show an edge shadow, which
meets NN/g's "visibly signaled" bar. The problem is **what** is hidden.

| Table | iPhone 14 (visible / full width) | Hidden | iPad portrait |
|---|---|---|---|
| Nodes | 324 / 841 | **61%** (Role, Hardware, Last heard off-screen) | 768 / 841 |
| Firehose | 324 / 892 | **64%** (Type and "What it said" off-screen) | 768 / 892 |
| Traceroutes | 324 / 756 | **57%** | fits |
| Node → Packet timeline | 324 / 798 | 59% | 768 / 798 |
| Node → Heard by | 324 / 579 | 44% (#260) | fits |
| Stats → Nodes worth a look | 324 / 594 | 45% | fits |
| Dashboard → Recently heard, Busiest | 324 / 431, 324 / 425 | 25%, 24% | fits |

The whole document never scrolls sideways on any page or device.

### 2.5 Nothing is sticky

- On phones the top bar (brand and menu button, 61 px) scrolls away with the
  page.
- After scrolling 1,200 px on the dashboard, firehose, chat and RF, the menu
  button and the page's Live toggle were both above the viewport.
- Page lengths on an iPhone 14: Firehose **12 screens**, node page 7.1, stats
  6.1, dashboard 4.9, chat 4.8.
- Getting to another page from the bottom of the firehose means scrolling
  about 10,000 px back up. iOS has a tap-the-status-bar shortcut that scrolls
  to the top, but emulation cannot test it.

### 2.6 Text size

- The body size is **15 px** (`--font: 15px/1.5`). Tables are 0.88rem
  (14 px), table headers 0.75rem (12 px), and tags about 11.5 px.
- Measured by characters, **96–100% of the text on every page is under
  16 px**.
- Pages where most text is under 14 px:

  | Page | Share under 14 px |
  |---|---|
  | Gaps | 90% |
  | Planner | 87% |
  | Config | 80% |
  | Map | 75% |
  | Graph | 70% |
  | RF | 68% |
  | Stats | 67% |

- The smallest text is 11.2 px (the nodes filter count badge). Tags such as
  `direct` and `Neighbor info 2.5x` are 11.5 px.
- Pinch zoom is allowed (the viewport meta is conformant). Nothing *needs*
  zooming to be legible at these sizes, but it is below the 16 px the brief
  names for body copy.

### 2.7 Hover-only information

- **CSS.** The stylesheets have 36 `:hover` rules outside Leaflet's own. Only
  3 change visibility, and none hides essential content:
  - the nav icon opacity;
  - the sort arrow going from 0.7 to 1 opacity;
  - the reaction-sender opacity.
- **Leaflet tooltips** (gaps, RF, siting). Leaflet 1.9.4 binds `click` as
  well as `mouseover` for non-permanent tooltips (read from
  `vendor/leaflet.js`), so a tap opens them.
- **ECharts tooltips** also respond to a tap by default.
- **The real gap is `title` attributes.** A touch screen never shows them.

  | Page | `title`s | What only the title says |
  |---|---|---|
  | Chat, dashboard | 36 | The exact time behind "1h ago" (`time.when`). A timestamp link's title says "Open packet 100017". |
  | Stats | 131 | What a tag means: "Neighbor info 2.5x" → "every 2.4 h, default 6 h" (75 tags). "up 15.7 days" → what uptime means (17). |
  | Node page | 102 | **Which health check each coloured dot is** ("Heard over the air: Unknown", 6 dots). The raw port name behind each packet type (49). |
  | Nodes | 51 | What the `gateway` tag means (13). The raw role enum (19). |
  | Firehose | 450 | The full date behind each time, the node ID behind each name, and the raw port name behind each type. |

- The node IDs and raw enums are nice to have. The health-dot meanings, the
  stats tag meanings and the exact message times are information a phone
  reader cannot get any other way (the health dots do have a *View all checks*
  link).

### 2.8 Load on a phone connection (Chromium, throttled, cold)

| Page | Slow 4G: FCP / data shown | Fast 4G: FCP / data shown | Transferred |
|---|---|---|---|
| Dashboard | 1.70 s / 6.13 s | 0.57 s / 1.98 s | 885 kB, 44 requests |
| Nodes | 1.62 / 5.63 | 0.58 / 1.82 | 882 kB |
| Chat | 1.72 / 5.72 | 0.64 / 1.76 | 883 kB |
| Map | 1.45 / 5.89 | 0.60 / 1.90 | 884 kB (no tiles) |
| Firehose | 1.72 / 5.78 | 0.57 / 1.53 | 884 kB |
| Stats | 1.70 / 6.35 | 0.60 / 2.12 | 887 kB |
| Node page | 1.45 / not settled¹ | 0.61 / not settled¹ | 885 kB |

¹ My "first data" probe did not settle on the node page under throttling. It
waits for no visible `.loading` element. Unthrottled, there were none after
10 s, so the page does finish. Treat its number as unmeasured.

**Every page downloads the same bundle.** All scripts are synchronous at the
end of `<body>`, and the "data shown" time tracks the `load` event within
50 ms on every page. The bundle includes:

- ECharts, 1.03 MB raw / **327 kB gzipped**, the largest single asset;
- `app.js`, 128 kB gzipped;
- Leaflet, 42 kB;
- the config checker's protobuf libraries, 25 kB.

So Nodes and Chat, which draw no chart, wait for the chart library before they
show a row. The HTML itself is 33 kB gzipped and paints its shell at about
1.5–1.7 s on slow 4G.

### 2.9 Motion and contrast

- **Reduced motion.** `prefers-reduced-motion` is honoured well in CSS: it
  near-zeroes animations and transitions (`app.css` 1415) and turns off the
  preset thumb slide. The live map reads it as the default of its *Motion*
  toggle.
  - **Not covered:** ECharts' own entry and update animations (no
    `animation: false` anywhere), and Leaflet's zoom and fade animations
    (`zoomAnimation` and `fadeAnimation` stay at their defaults). Apple's HIG
    asks for zooming and scaling in particular to be reduced.
- **Contrast.** There is no `prefers-contrast` rule and no `forced-colors`
  rule anywhere in the site's CSS or JS.

---

## 3. Per page

All numbers are from the iPhone 14 (390 × 844, WebKit) unless stated.

- **Header** is the share of the first screen above the first content, shown
  for SE / iPhone 14 / iPhone 14 with bars / Android / iPad portrait.
- **Small** is the number of undersized targets (<44 px), excluding the skip
  link and WebKit `select` artefacts, with the count under 24 px in brackets.
- **Screens** is the page length in viewport heights.

### Dashboard

- **Header:** 37 / 18 / 23 / 17 / 14%. **Small:** 10 (0). **Screens:** 4.9.
  **Under 16 px:** 99%.
- The four stat cards take **292 px (35% of the first screen) to show four
  numbers**. Each card is about 150 px tall for a two-line figure.
- Both tables scroll sideways by about 25%. *Recently heard* hides its last
  column, which is only a sliver off-screen.
- 7 of the 10 small targets are `?` info buttons (24 × 44). They pass WCAG
  2.5.8 but miss 44.
- 15 controls are below the fold, all of them in the feeds and tables further
  down. None is a page control.

### Nodes

- **Header:** 52 / 31 / 40 / 29 / 14%. **Small:** 6 (0 on Android). **Hidden
  sideways:** 61%.
- On a phone you see the name and a clipped node ID (`!0a51b00`). **Role,
  hardware and *Last heard* are all off to the right.** Last heard is the
  column a regular most wants.
- The search box, the time window select, the role select, *Gateways* and
  *Filters (2)* take 168 px.
- Meshview (upstream templates) switches its node list to cards below 768 px.
  It is the one responsive pattern that project has, and the right model here.

### Chat

- **Header:** 60 / 41 / 52 / 38 / 23%. **Small:** 38 (24). **Screens:** 4.8.
- The worst page for small targets:
  - **22 timestamp links** at 41 × 19;
  - channel title links 24 tall;
  - three *more* links 32 tall;
  - the reaction pill at 49 × 24.
- The page head wraps badly on a phone. *24 h / 7 d / 30 d* sit on one line,
  *Dates…* floats to the right with a gap, and *Live* drops to a row of its
  own.
- The exact time of a message is only in a `title`.

### Traceroutes

- **Header:** 27 / 18 / 23 / 17 / 14%. **Small:** 2 real ones plus 5 row
  links (whole row is the target). **Hidden sideways:** 57%.
- The page head is compact. The problem is the table.

### Map

- **Header:** 50 / 26 / 35 / 23 / 13%. **Small:** 8 (2), plus every dot
  (§2.2).
- **The page scrolls itself 235 px down on load** in WebKit. After load,
  `scrollY` was 235 and the page head sat at y = −158. The Traffic, Packet
  types, Live traceroutes, Neighbor links, Motion and Live controls start
  above the viewport. The iPad landscape screenshot shows the same thing.
  - I could not find the cause. There is no `scrollTo`/`scrollIntoView` on
    this path.
  - It may be deliberate, putting the map first, but a reader arriving on a
    phone does not know the controls exist.
- The role filter buttons (the legend under the map) start at y = 881, below
  the fold.
- On iPad landscape the *Key* is open by default and covers about 40% of the
  map's width.
- The popup disappears on every live refresh. That is in flight as #264.

### Graph

- **Header:** **74** / 44 / 56 / 36 / 20%. **Small:** 2 on Android (the rest
  are WebKit selects).
- Six controls are stacked and right-aligned (Window, Find a node, Layout,
  View, Show unconfirmed links, Show unjudged links, Reset layout) above the
  canvas. On an iPhone SE, three quarters of the first screen is controls.
- *Full screen* is 30 px tall.

### Coverage

- **Header:** 48 / 33 / 41 / 30 / 18%. **Small:** 4 (1): the Leaflet zoom
  buttons and the attribution link.
- Mostly fine. 53% of its text is under 14 px.

### Planner

- **Header:** 53 / 35 / 45 / 27 / 20%. **Small:** 4 on Android.
- **Below the fold on a phone:** the preset select (y = 882), the antenna and
  height inputs (934–1082). A reader sets a site on the map and then has to
  scroll to the form to change what they are modelling.
- 87% of its text is under 14 px (form labels at 12.2 px).
- The planner table's row highlight on the map is bound to `mouseenter`
  (`siting.js` 331). A tap toggles the row open. Whether iOS fires the
  highlight on a tap is unverified.

### Gaps

- **Header:** 64 / 41 / 52 / 38 / 24%. **Small:** only the menu button.
- 90% of its text is under 14 px, the highest share on the site.
- *Find a node* is at y = 1208, two screens down.
- Its values and key are being changed in #265.

### Config check

- **Header:** 33 / 20 / 25 / 19 / 13%. **Small:** none that matter. The file
  input is visually hidden behind a large drop zone.
- *Build a new config* is below the fold (y = 1041).

### Weekly check-in (meshnet)

- Measured after its data appeared (§1.2).
- **Header:** **94** / 49 / 63 / 44 / 28%. **Screens:** 2.9.
- On an iPhone SE nearly the whole first screen is the title, a two-line
  explanation and the Tag / weeks / Show form.
- The node-name buttons are 19–22 px tall on iPad landscape.
- Being rebuilt in #262.

### Firehose

- **Header:** 50 / 31 / 40 / 29 / 19%. **Small:** 5 real ones plus 151 row
  links. **Hidden sideways:** **64%**. **Screens:** **12**.
- On an iPhone SE you see only *Time* and *From*. What the packet was, and
  what it said, are off to the right on every row.
- With a 12-screen page and nothing sticky, the Live toggle and filter are
  gone after the first screen.

### RF

- **Header:** **100** / 57 / 72 / 50 / 31%. **Small:** 4.
- On an iPhone SE the first screen is entirely the title, a four-line
  description, five source toggles, the Table button, Window and Live. Not
  one data element is visible.
- The disclaimer ("not air traffic control") comes before the data. The map
  follows the source list.

### Statistics

- **Header:** 27 / 18 / 23 / 17 / 14%. **Small:** 11 (0), mostly `?`
  buttons. **Screens:** 6.1.
- **131 `title`s.** The meaning of every "2.5x" tag is title-only. 29% of the
  text is under 12 px, the most on the site.

### Node detail (`#node/!0a51e004`)

- **Header:** 34 / 23 / 29 / 23 / 14%. **Small:** 21 real ones (11 `?`
  buttons, the Leaflet zoom buttons, *Full screen*) plus 48 timeline row
  links. **Screens:** 7.1.
- There are 13 panels in one column on a phone: Identity, Device, Health,
  Activity, Weather, Where it is, Links and routes, What it sent, Messages,
  Neighbors, Heard by, Signal, Packet timeline. There is no in-page navigation
  or collapse, so reaching the *Packet timeline* means scrolling past y = 3760.
- The health dots explain themselves only in `title`s.
- On iPad portrait the page lays out three columns. "CLIENT_BASE" breaks
  mid-word into "(CLIENT_BASE" and ")" on its own line, and *Last heard* wraps
  onto three lines.
- The tables (#255, #260), the packets panel (#259), the mesh-graph button
  (#258), the tooltips (#256), the red values (#254) and the furthest-heard
  distance (#257) are all in flight.

### The menu drawer

- The 14 links are 44 px each, and the drawer is 838 px tall.
- On an iPhone 14 the **Preset switch and the Settings link are below the
  fold of the drawer** (Settings at y = 863). With the Safari bars showing,
  even *Updated* is below it.
- The drawer lists all 14 pages with equal weight. The site has no usage data
  to say which ones a phone reader uses most. See §4.1.

---

## 4. Research: which mobile patterns fit this site

Each pattern is judged on whether it helps the readers of **this** site, a
mesh dashboard of maps, live feeds and node lists, not on whether it is in
fashion. Some sources could not be read directly:

- The live Meshview (`view.azmsh.net`) redirects every page to a Keycloak
  login (`302 → auth.azmsh.net`, checked 2026-09-26), so it was read from its
  upstream templates (`pablorevilla-meshtastic/meshview`, `master`).
- Apple's HIG was read from its documentation JSON.
- Material 3 wording comes from search excerpts, because the pages do not
  render without JavaScript.
- Anything marked *unverified* is general knowledge I could not confirm from a
  source.

### 4.1 Bottom navigation for the most-used pages, with a "More" sheet

- **What the sources say.**
  - Apple (HIG, *Tab bars*): "Aim for a default list of five or fewer", "use
    single words whenever possible", keep it visible across sections, and
    "avoid overflow tabs… The More tab makes it harder for people to reach and
    notice content".
  - Material 3: use a navigation bar for 3–5 destinations on compact widths
    (<600dp), and a navigation rail for medium widths.
  - NN/g (*Find navigation on mobile, even hamburger*): visible navigation was
    used in 89% of sessions, against 44–56% for hidden navigation, and found
    sooner (21–24 s against 33 s).
  - Hoober (UXmatters 2013, 2017): 49% of people hold a phone one-handed.
    Later work found people prefer to touch the *centre*, and corner targets
    need about 12 mm against about 7 mm in the centre. So "bottom is easy"
    holds for full-width bars with large items, not for small corner icons.
- **How comparable apps do it.**
  - The Meshtastic Apple app has a bottom tab bar: Connect, Messages, Nodes,
    Map, Settings (meshtastic.org docs).
  - The Meshtastic Android docs name the same sections. That they are a bottom
    bar is *unverified*.
  - Meshview uses a centred row of text links. tar1090 has no navigation;
    it is one page.
- **Web caveat.**
  - Safari 15 and later can place its own toolbar at the bottom.
  - iOS 26's default "compact" Safari floats a detached toolbar at the
    bottom. Community reports (not WebKit documentation) say this breaks
    `position: fixed; bottom: 0` bars, leaving a gap or overlapping them, and
    that `env(safe-area-inset-bottom)` does not account for it.
  - A web bottom bar therefore needs testing on a real iOS 26 device before it
    ships.
- **Verdict for this site: probably helps, but not first.**
  - Fourteen destinations do not fit a bar. A bar of four plus a *More* that
    opens the current drawer would put the busiest pages one tap away instead
    of two.
  - It would also fix the "menu button scrolled away" problem (§2.5).
  - But which four is a guess without usage data, and the iOS 26 risk is real.
  - Do §5 item 6 (a compact sticky top bar) first. It solves reachability with
    no iOS toolbar risk.
  - Choosing the four is a decision for Will. My suggestion, by what the
    native Meshtastic apps put in their bars: Map, Nodes, Chat, Dashboard,
    then More.

### 4.2 Bottom sheets instead of popups and modals

- **What the sources say.**
  - NN/g (*Bottom sheets*): support Back, include a visible Close button, do
    not stack sheets, keep them to brief tasks, and "do not use a bottom sheet
    to replace typical page-to-page user flows".
  - Apple (*Sheets*): a medium detent at "about half" height for progressive
    disclosure, with a grabber that cycles detents.
  - Material 3: *standard* (non-modal) sheets "co-exist with the screen's
    main UI region", which is exactly a sheet over a map that stays pannable.
- **How comparable apps do it.** Google Maps and Flightradar24 both open the
  selected item in a sheet over the map (FR24: swipe up once for the panel,
  again for the graph).
- **Web caveats.**
  - `<dialog>` is supported everywhere current.
  - The Popover API's tap-outside dismissal was broken on iOS 17 to 18.2
    (fixed in 18.3, WebKit bug 267688). That matters because the site's `?`
    tooltips are popovers.
  - A sheet's scroller needs `overscroll-behavior: contain`.
- **Verdict: helps on the map pages, specifically.**
  - The node popup today is 188 × 137 px, with a 24 px close button. It covers
    the map around the dot and disappears on every refresh (tracked in #264).
  - A non-modal sheet (peek: name, role, last heard, *Open node*; half:
    today's node summary) keeps the map usable and gives a 44 px close.
  - Not for filters, which are short enough for the existing inline panels,
    and not for navigation (NN/g).

### 4.3 Cards or priority columns instead of wide tables

- **What the sources say.** NN/g (*Mobile tables*): lock the first column,
  let people choose columns, use accordions or one-item views for records,
  and allow sideways scroll only when it is clearly signalled.
- **How comparable apps do it.**
  - Meshview switches its node list to cards below 768 px.
  - The Meshtastic Apple app shows node rows as two-line cards, with a
    Complete/Compact density toggle.
  - tar1090 halves the number of table rows on mobile.
- **Verdict: helps on Nodes, Firehose and Traceroutes.**
  - These hide 57–64% of their width, including the columns a phone reader
    wants.
  - Nodes and Firehose rows are records ("a node", "a packet"), so a two-line
    card is right: name and badge, then role · last heard, or type · what it
    said.
  - Traceroutes and the stats tables are comparisons across rows, so keep the
    table, stick the first column, and drop low-priority columns below 40rem.
  - The node page's tables are already in #255, #259 and #260.

### 4.4 A compact sticky header that collapses on scroll

- **What the sources say.**
  - NN/g (*Sticky headers*): keep them small, opaque and at least 1 cm tall
    for targets. Their good example had a content-to-chrome ratio of 13:1;
    their bad one had 2:1. A "partially persistent" header that reappears on
    scroll-up works "moderately well".
  - Apple: a large title collapses to a standard title on scroll.
  - The iOS 26 reports above say Safari now tints its own chrome from fixed
    or sticky elements at the screen edges.
- **Verdict: helps everywhere, and it is the cheapest reachability fix.**
  - A 48–56 px bar holding the menu button, the page name, and the live dot
    with its "Updated" time, reappearing on scroll-up, fixes §2.5 without a
    bottom bar.
  - The page-head controls (Live, filters) should not be sticky. That would
    rebuild the 40–60% header problem on every screen.

### 4.5 Pull to refresh instead of the Live toggle

- **What the sources say.**
  - The browser owns the pull gesture. `overscroll-behavior-y: contain` turns
    its pull-to-refresh off (Chrome developer blog, MDN).
  - iOS Safari's support is partial.
  - Pull-to-refresh is criticised for triggering by accident while scrolling
    up.
- **How comparable apps do it.**
  - For live feeds, the common pattern is to keep the reader's place and show
    a "N new ↓ / Jump to latest" pill. Slack and Discord do this, the
    Meshtastic Android app added a scroll-to-bottom button in 2.6.30, and the
    Colorado-Mesh client added "Jump to Latest".
  - Meshview's firehose uses an explicit **Pause** button.
- **Verdict: no to pull-to-refresh, yes to a "new items" pill.**
  - These pages already refresh themselves every 15 s. A pull gesture would
    refresh something that is already live, and it would compete with the
    browser's reload.
  - The Live toggle already works like Meshview's Pause.
  - What is missing is the firehose telling a reader who has scrolled down
    that N packets arrived above them.

### 4.6 Skeleton loading instead of "Loading"

- **What the sources say.**
  - NN/g (*Skeleton screens 101*): no indicator under 1 s; skeletons for
    full-page loads up to about 10 s; and only content-shaped skeletons help —
    a header-and-footer frame "is essentially equivalent to a spinner".
  - Viget's test (n = 136) found skeletons did *worst* on perceived speed.
    Another study found the opposite.
- **Verdict: low value here.**
  - The waits are 1.5–2 s on fast 4G, so the gain is small and the evidence
    is mixed.
  - The real fix for the 6 s slow-4G wait is not downloading ECharts on
    pages that do not use it (§5 item 12).
  - Revisit only for the node page, where several panels load separately and each says "Loading".

### 4.7 Safe-area-aware layout

- **What the sources say.** WebKit (*Designing websites for iPhone X*):
  with `viewport-fit=cover`, you must pad with `env(safe-area-inset-*)`,
  ideally as `max(12px, env(…))`.
- **Status here.** The site already declares `viewport-fit=cover` and reads
  all four insets into custom properties.
- **Verdict: already in place.** It cannot be verified without a notched
  device (§1.2). If a bottom bar or sheet is added (4.1, 4.2), it must add
  `env(safe-area-inset-bottom)`, and it still needs the iOS 26 check.

### 4.8 `prefers-reduced-motion` and `prefers-contrast`

- **What the sources say.**
  - WCAG 2.3.3 (AAA): motion triggered by interaction can be disabled.
  - Apple asks for less zooming and scaling when Reduce Motion is on.
  - `prefers-contrast` is supported from Safari 14.1, Chrome 96 and
    Firefox 101.
- **Verdict: small and worth it.**
  - Extend reduced motion to ECharts and Leaflet's zoom animation (§2.9).
  - Add a `prefers-contrast: more` block that strengthens `--muted`, `--line`
    and the table-header colour. Most of the small text on this site is in
    the muted colour.

### 4.9 Touch target size, and hover on touch

- **What the sources say.**
  - WCAG 2.5.8 (AA): at least 24 × 24 CSS px, or spaced so a 24 px circle
    around each target does not meet another.
  - WCAG 2.5.5 (AAA): 44 × 44.
  - Apple: 44 × 44 pt.
  - Material: 48 × 48 dp.
  - NN/g: tooltips "are not normally available on touchscreens"; users
    "shouldn't need to find a tooltip in order to complete their task".
- **How comparable apps do it.** meshmap.net hides hover tooltips under
  `(hover: none)` and relies on tap popups. tar1090 disables its hover info
  block on mobile and widens marker hit tolerance.
- **Verdict: this is the largest win.** See §2.1–2.3 and §2.7. Key the touch
  sizes to `(pointer: coarse)`, not width. Give the map a hit tolerance. Move
  the three kinds of title-only meaning into something a tap can reach.
- **Do not copy** meshmap.net and tar1090's `user-scalable=no` /
  `maximum-scale=1`. The site is right to allow zoom (WCAG 1.4.4, and the
  comment in `index.html` already says so).

### 4.10 What the comparable apps agree on

- Map-first, with floating controls.
- The selected item in a sheet (FR24, Google Maps).
- One persistent control at the bottom for time or live (Windy's and
  RainViewer's timeline players).
- Tap instead of hover (meshmap, tar1090).
- A tab bar of five or fewer in the native Meshtastic apps.
- Density choices for node lists (Meshtastic Apple's Compact/Complete).

The live map is the page closest to that shape already. Its watch mode is
map-first and full-screen.

### Sources

- Apple HIG, [Tab bars](https://developer.apple.com/design/human-interface-guidelines/tab-bars), [Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets), [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars), [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Material 3, [Navigation bar](https://m3.material.io/components/navigation-bar/guidelines), [Navigation rail](https://m3.material.io/components/navigation-rail/overview), [Bottom sheets](https://m3.material.io/components/bottom-sheets/guidelines)
- NN/g: [Hamburger vs visible nav](https://www.nngroup.com/articles/find-navigation-mobile-even-hamburger/), [Bottom sheets](https://www.nngroup.com/articles/bottom-sheet/), [Mobile tables](https://www.nngroup.com/articles/mobile-tables/), [Sticky headers](https://www.nngroup.com/articles/sticky-headers/), [Skeleton screens](https://www.nngroup.com/articles/skeleton-screens/), [Tooltips](https://www.nngroup.com/articles/tooltip-guidelines/), [Saving scroll position](https://www.nngroup.com/articles/saving-scroll-position/)
- S. Hoober, UXmatters: [2013](https://www.uxmatters.com/mt/archives/2013/02/how-do-users-really-hold-mobile-devices.php), [2017](https://www.uxmatters.com/mt/archives/2017/03/design-for-fingers-touch-and-people-part-1.php)
- W3C: [2.5.8 Target size (minimum)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), [2.5.5 Target size (enhanced)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html), [2.3.3 Animation from interactions](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html), [1.4.13 Content on hover or focus](https://www.w3.org/WAI/WCAG22/Understanding/content-on-hover-or-focus.html)
- WebKit, [Designing websites for iPhone X](https://webkit.org/blog/7929/designing-websites-for-iphone-x/); web.dev, [viewport units](https://web.dev/blog/viewport-units); Chrome, [overscroll-behavior](https://developer.chrome.com/blog/overscroll-behavior); MDN, [overscroll-behavior](https://developer.mozilla.org/en-US/docs/Web/CSS/overscroll-behavior), [hover](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/hover); MDN browser-compat-data (popover, prefers-contrast, env())
- iOS 26 Safari bottom bar reports (community, not WebKit docs): [1ar.io](https://1ar.io/updates/safari-26-liquid-glass-web/), [9to5Mac](https://9to5mac.com/2025/09/15/iphone-ios-26-safari-new-compact-design/); Safari 15 bottom bars, [Samuel Kraft](https://samuelkraft.com/blog/safari-15-bottom-tab-bars-web)
- Meshtastic docs: [Apple getting started](https://meshtastic.org/docs/software/apple/user/getting-started/), [Apple nodes](https://meshtastic.org/docs/software/apple/user/nodes/), [Apple map](https://meshtastic.org/docs/software/apple/user/map/), [Android nodes](https://meshtastic.org/docs/software/android/user/nodes/), [Android map](https://meshtastic.org/docs/software/android/user/map-and-waypoints/), [Android 2.6.30 release](https://github.com/meshtastic/Meshtastic-Android/releases/tag/2.6.30)
- Meshview upstream templates: [pablorevilla-meshtastic/meshview](https://github.com/pablorevilla-meshtastic/meshview) (`nodelist.html`, `node.html`, `firehose.html`)
- tar1090: [wiedehopf/tar1090](https://github.com/wiedehopf/tar1090) (`early.js`, `script.js`); Flightradar24 [support article](https://support.fr24.com/support/solutions/articles/3000118472-how-to-view-a-single-flight-playback-from-the-flightradar24-app-); Windy [article](https://www.windy.com/articles/32409); RainViewer [App Store listing](https://apps.apple.com/us/app/rainviewer-weather-radar-live/id980123924); Colorado-Mesh [mesh-client PR #1029](https://github.com/Colorado-Mesh/mesh-client/pull/1029)
- Skeleton research: [Viget](https://www.viget.com/articles/a-bone-to-pick-with-skeleton-screens), [ResearchGate paper](https://www.researchgate.net/publication/326858669_The_effect_of_skeleton_screens_Users'_perception_of_speed_and_ease_of_navigation)

---

## 5. Prioritised changes

- **Order** is value to a phone or tablet reader against effort and risk.
- **Effort:** S is under half a day, M is one to two days, L is more.
- **In flight** means an open issue already covers the change, so it is not
  proposed again.

### P1: small, high value, low risk

**1. Map dots: give them a finger-sized hit area on touch screens**

- **Problem:** dots are 5–13 px across, and the canvas renderer's
  `tolerance` is 0 (§2.2).
- **Change:** under `(pointer: coarse)`, create the canvas renderer with a
  `tolerance` of about 12–15 px, so the effective target is at least 44 px.
  Where dots overlap, Leaflet picks the topmost.
- **Pages:** map, node page map, coverage, gaps, planner, RF.
- **Effort:** S. **Risk:** low. With dense clusters a tap can pick a
  neighbour; test on the Phoenix cluster.
- **Related:** #264 (popup closing) is separate.

**2. Key touch sizing to `(pointer: coarse)`, not width**

- **Problem:** an iPad in landscape has 69 targets under 44 px on the
  dashboard, 90 on chat and 66 on stats, against 10, 38 and 11 on a phone.
  Its nav links are 38 px, its `?` buttons 24 × 24, and its chat names 19 px
  (§2.1).
- **Change:** move the phone target-size rules into a `(pointer: coarse)`
  block, or duplicate them there.
- **Pages:** all.
- **Effort:** S–M. **Risk:** low. Desktop with a mouse is untouched. Touch
  laptops get the larger size, which is correct.

**3. Enlarge the fixed-size controls on touch**

- **Problem:**
  - Leaflet zoom buttons 30 × 30 (5 pages);
  - map popup close 24 × 24;
  - *Full screen* 30 tall;
  - map *Key* 29 tall;
  - *Watch mode* 30 wide;
  - reaction pill 24 tall;
  - menu button 40 wide;
  - drawer Settings link 37 tall (§2.3).
- **Change:** raise each to at least 44 px on `(pointer: coarse)`.
- **Pages:** all map pages, dashboard, stats, graph, node, chat, the drawer.
- **Effort:** S. **Risk:** low.

**4. Chat timestamps: a real tap target, and the exact time on tap**

- **Problem:** 22 timestamp links per page at 41 × 19. The exact time is only
  in a `title` (§2.7, chat).
- **Change:**
  - Pad the link's hit area to 44 px tall.
  - Show the exact time in the packet it opens, or as the link's visible text
    when the message is older than a day.
- **Pages:** chat, dashboard feed.
- **Effort:** S. **Risk:** low.

**5. Stop the map page scrolling itself on load, or say why it does**

- **Problem:** `scrollY` is 235 after load. All seven map controls start
  above the viewport on a phone and on an iPad (§3, Map).
- **Change:** find the cause. If the jump is intended, keep it but put a
  one-line control strip or a *Controls* button at the top of the map.
- **Pages:** map.
- **Effort:** S to investigate. **Risk:** low.

**6. A compact sticky top bar on phones**

- **Problem:** nothing is sticky. After 1,200 px the menu button and Live are
  gone, and the firehose is 12 screens long (§2.5).
- **Change:** make the 61 px brand bar sticky (opaque), holding the menu
  button and the live dot with its "Updated" time. Optionally hide it on
  scroll-down and show it on scroll-up (NN/g "partially persistent").
  Page-head controls stay in the page.
- **Pages:** all, below 60rem.
- **Effort:** S–M. **Risk:** medium on iOS 26, because of the reports about
  Safari tinting from edge elements. Needs the real-device check in §6.

### P2: medium effort, clear value

**7. Nodes list as cards on phones**

- **Problem:** 61% of the table is hidden sideways, and *Role* and *Last
  heard* are off-screen at 390 px (§2.4).
- **Change:** below 40rem, render each node as a two-line card: name and
  short name, then role · last heard · gateway. Meshview's node list does
  this below 768 px.
- **Pages:** nodes, and the same component on the dashboard's *Recently
  heard*.
- **Effort:** M. **Risk:** low. The table stays at other widths.

**8. Firehose rows as cards on phones**

- **Problem:** 64% hidden. On an SE only *Time* and *From* are visible
  (§3, Firehose).
- **Change:** below 40rem, show a two-line row: time · from → to, then
  type · what it said.
- **Pages:** firehose.
- **Effort:** M. **Risk:** low.

**9. Traceroutes table: sticky first column and priority columns**

- **Problem:** 57% hidden.
- **Change:** stick the Time column, and drop the least-used columns below
  40rem behind the row link.
- **Pages:** traceroutes, and the stats *Nodes worth a look* table (45%
  hidden).
- **Effort:** S–M. **Risk:** low.

**10. Fold page-head controls behind a *Filters* button on phones**

- **Problem:** controls take up most of the first screen on some pages:

  | Page | iPhone 14 | iPhone SE |
  |---|---|---|
  | Graph | 44% | 74% |
  | RF | 57% | 100% |
  | Chat | 41% | 60% |
  | Gaps | 41% | 64% |
  | Weekly check-in | 49% | 94% |

- **Change:** below 40rem, keep Live and one primary control visible. Put the
  rest behind *Filters (n)*, the pattern Nodes already uses. Shorten the
  descriptions to one line, with the rest behind the `?`.
- **Pages:** graph, RF, chat (fix the wrap as well), gaps. Weekly check-in is
  in flight (#262).
- **Effort:** M, one page per PR. **Risk:** low to medium. Hidden filters are
  easier to miss, so show the active count.

**11. Make title-only meanings reachable by tap**

- **Problem:** a touch screen never shows `title`s. These carry the meaning
  of:
  - the node page's health dots (6);
  - the stats tags (75) and uptime notes (17);
  - the `gateway` tag (13);
  - the exact message times (§2.7).
- **Change:** use the existing `?` popover, or visible text, for each kind.
  Leave the redundant titles (node IDs, raw enums) as they are.
- **Pages:** node, stats, nodes, chat.
- **Effort:** M. **Risk:** low.
- **Related:** coordinate with #256 (node tooltips, in flight).

**12. Load ECharts only on pages that draw a chart**

- **Problem:** every page downloads 327 kB gzipped of ECharts (37% of the
  885 kB). On slow 4G, content arrives at 5.6–6.3 s on every page, including
  Nodes and Chat, which draw no chart (§2.8).
- **Change:** load `echarts.min.js` on first use. Do the same for the config
  checker's protobuf and YAML libraries on `#config`.
- **Pages:** all.
- **Effort:** M. **Risk:** medium. The CSP, the load-order assumptions in
  `app.js`, and the e2e all need checking.

**13. Dashboard stat cards as one compact row**

- **Problem:** four numbers take 292 px, 35% of the first screen.
- **Change:** below 40rem, show a 2 × 2 or 4 × 1 strip about 120 px tall.
- **Pages:** dashboard, stats.
- **Effort:** S. **Risk:** low.

**14. Move the drawer's Preset and Settings above the fold**

- **Problem:** in an 844 px drawer the preset switch and Settings are below
  the fold, and with Safari's bars showing so is *Updated*.
- **Change:** tighten the link rows to 44 px with less padding, or put the
  preset switch at the top of the drawer. Settings could sit beside the
  close button.
- **Pages:** drawer.
- **Effort:** S. **Risk:** low.
- **Related:** #232 (settings in the header) touches the same area.

### P3: worth doing, lower urgency or needs a decision

**15. A "N new" pill on the firehose when scrolled away from the top**

- **Problem:** a reader two screens down cannot see that new packets arrived
  above them.
- **Change:** show a sticky "12 new ↑" pill that scrolls back to the top.
- **Pages:** firehose, and possibly traceroutes.
- **Effort:** M. **Risk:** low.
- **Note:** pull-to-refresh is *not* recommended (§4.5).

**16. Map node detail as a non-modal bottom sheet on phones**

- **Problem:** the popup is 188 × 137 with a 24 px close, sits over the map,
  and disappears on refresh (tracked in #264).
- **Change:** below 40rem, open the node summary in a sheet anchored to the
  bottom, with a peek state and a half state, a 44 px close, and Back
  support.
- **Pages:** map, coverage, gaps.
- **Effort:** L. **Risk:** medium: iOS 26 bottom-bar reports, and gesture
  conflicts with map panning.
- **Related:** do it after #264 lands. Item 3's bigger close button is the
  cheap interim.

**17. Bottom navigation bar (four pages plus More)**

- **Problem:** reachability (§2.5), and the fact that hidden navigation gets
  used less (NN/g).
- **Change:** below 40rem, a bottom bar with four pages plus *More*, where
  *More* opens the existing drawer.
- **Pages:** all.
- **Effort:** L. **Risk:** high on iOS 26 Safari, and it depends on item 6.
- **Needs Will:** which four pages. Suggested: Map, Nodes, Chat, Dashboard.
  Ship item 6 first and decide from how that feels.
- **Decided (Will, 2026-10-08):** the suggested four, then More. Built in
  #282. The trigger and the reasons are in the PR and in `tab-bar.js`.

**18. Body text at 16 px on touch screens**

- **Problem:** the body is 15 px, and 96–100% of every page's text is under
  16 px. Several pages are 70–90% under 14 px (§2.6).
- **Change:** 16 px body under `(pointer: coarse)`, and raise the 11–12 px
  tags and headers to at least 12.5 px.
- **Pages:** all.
- **Effort:** M. **Risk:** medium. Every page gets longer, and every table
  gets wider (which makes items 7–9 more pressing).
- **Needs Will:** this is a look-and-feel change.
- **Decided (Will, 2026-10-08):** build it. Built in #283. The body is
  16 px and the smallest text is .78 rem (12.48 px) under
  `(pointer: coarse)`. Tables keep their width, because a rem size follows
  the root and the root stays 16 px. The measurements are in the PR.

**19. Reduced motion for charts and map zoom**

- **Problem:** ECharts animations and Leaflet's zoom and fade animations
  ignore `prefers-reduced-motion` (§2.9).
- **Change:** set `animation: false` in `CHART_BASE`, and
  `zoomAnimation` / `fadeAnimation: false` on Leaflet maps, when the query
  matches.
- **Pages:** all charts and maps.
- **Effort:** S. **Risk:** low.

**20. A `prefers-contrast: more` block**

- **Problem:** there is none. Most small text is in `--muted`.
- **Change:** strengthen `--muted`, `--line` and the `th` colour under
  `prefers-contrast: more`, and add a `forced-colors` check.
- **Pages:** all.
- **Effort:** S. **Risk:** low.

**21. Node page: in-page navigation on phones**

- **Problem:** 13 panels over 7.1 screens, with the packet timeline at
  y = 3760 and no way to jump.
- **Change:** a sticky row of section chips (Identity · Health · Activity ·
  Map · Links · Timeline), or collapse the lower panels.
- **Pages:** node.
- **Effort:** M. **Risk:** low.
- **Related:** coordinate with the node-page issues #254–#260.

**22. iPad portrait: fix the node page's three-column squeeze**

- **Problem:** "(CLIENT_BASE" and ")" break across lines, and *Last heard*
  wraps onto three lines at 834 px.
- **Change:** use two columns between 40rem and 62rem, or let the identity
  panel span two columns.
- **Pages:** node.
- **Effort:** S. **Risk:** low.

### Already in flight (not proposed again)

| Issue | Covers |
|---|---|
| #253 | iPad top overscroll band. Cannot be reproduced in emulation. |
| #254 | Node page: capitalise Unknown, red bad values |
| #255 | Node page: Activity table scrolls sideways |
| #256 | Node page: tooltips for Identity and Device fields |
| #257 | Node page: furthest-heard distance |
| #258 | Node page: *Open in mesh-graph* as a button |
| #259 | Node page: packets panel, control placement, infinite scroll |
| #260 | Node page: *Heard by* table scrolls sideways (measured 44% hidden) |
| #262 | Weekly check-in rebuild (its 49% / 94% header share is recorded above for whoever rebuilds it) |
| #264 | Map popup disappears on live refresh |
| #265 | Gaps: raw fractions, and the page needs a key |

---

## 6. For a real-device pass

These are the questions emulation could not answer (§1.2), in the order I
would check them:

1. iOS 26 Safari (compact tab bar): does a sticky top bar (item 6) tint or
   overlap correctly? Would a fixed bottom element (items 16, 17) be covered
   by the floating toolbar?
2. iPad Safari: the #253 overscroll band, and whether the safe-area padding
   lands correctly in both orientations.
3. On a real phone, the tap accuracy on map dots before and after item 1, in
   the Phoenix cluster.
4. Whether a tap fires the planner table's `mouseenter` highlight on iOS and
   Android.
5. The native `<select>` height on iOS Safari. WebKit on the Mac said 23 px
   and Chromium said 44 px.
6. Load time with real map tiles, on a real cellular connection.
