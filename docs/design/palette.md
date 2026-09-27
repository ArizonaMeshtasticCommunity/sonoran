# Colour palette and how to use it

This document is the reference for colour on every Sonoran page (#49).
The tokens live in `src/sonoran/web/static/app.css`. The light theme
(#50) gives every token a second value in `:root[data-theme="light"]`.

The contrast figures below are computed from the CSS, not estimated.
Re-run the check in section 8 after you change a value.

## 1. Rules

1. Never encode meaning in colour alone (WCAG 1.4.1). A state also has
   a word and a shape. A packet family also has a shape. A role also
   has a label in the key.
2. No colour comes from a number. The gaps page and the node page show
   a state for each signal, not a score with a colour on it.
3. `unknown` is its own colour and is never green. Not measured is not
   fine.
4. Use a token, never a raw value. A raw value has no light twin, so
   it breaks the theme switch.
5. Text meets 4.5:1 on the surface it sits on (WCAG 1.4.3). A mark on a
   map or a chart meets 3:1 (WCAG 1.4.11).
6. Data ramps do not change with the theme. The coverage signal ramp
   is data, and inverting it once drew it backwards (see the note
   above the basemap filter in `app.css`).

## 2. Surfaces

| Token | Dark | Light | Use |
| --- | --- | --- | --- |
| `--bg` | `#17100b` | `#f7f2ec` | Page background |
| `--panel` | `#221811` | `#ffffff` | Panel, card, table |
| `--panel-2` | `#2f2219` | `#f1e9e0` | A panel inside a panel, a hover |
| `--line` | `#422f23` | `#ddd0c2` | Borders and rules |

## 3. Text and accents

Ratios are against `--panel`.

| Token | Dark | Ratio | Light | Ratio | Use |
| --- | --- | --- | --- | --- | --- |
| `--text` | `#f6ece2` | 14.9 | `#25190f` | 17.1 | Body text. Floor 4.5:1 (WCAG 1.4.3). |
| `--muted` | `#b59c88` | 6.7 | `#6b5646` | 6.9 | Secondary text, labels, notes. Floor 4.5:1. |
| `--accent` | `#f4703f` | 6.0 | `#b8481f` | 5.3 | Links, focus, the one thing to act on. |
| `--map-link` | `#6ea9c9` | 6.8 | `#2c6a8f` | 5.9 | `--accent-2`: a different kind of thing. |

Use `--accent` for one thing on a screen: the thing to act on, or the
one value that matters. Use `--accent-2` (`--map-link`) when a second
kind of thing must stand apart from the first, for example a link
line beside an accent marker. Text on an accent fill uses
`--on-accent`.

## 4. Semantic status

One set for the whole site. The node health cards, the node page's
potential issues, the gaps page and the graph all use it. The alias
tokens name the meaning; the base tokens hold the value.

| Token | Dark | Ratio | Light | Ratio | Meaning |
| --- | --- | --- | --- | --- | --- |
| `--good` | `#8cb369` | 7.3 | `#3b7a1e` | 5.3 | `--status-ok` |
| `--warn` | `#edc04b` | 10.1 | `#8a6100` | 5.5 | `--status-warn` |
| `--bad` | `#ef6f5c` | 5.9 | `#b7352a` | 5.9 | `--status-bad` |
| `--role-stale` | `#7d6857` | 3.3 | `#857260` | 4.6 | `--status-unknown`. Marks only, never body text. |

Each state also carries a word and a shape: ok is a solid circle,
warn a double square, bad a solid square, unknown a dashed circle.
The word for unknown uses `--muted`, because `--status-unknown` is
dim by design and is not a text colour.

The node page's Identity and Device panels (#254) colour a value
`--warn` or `--bad` as text, which both tokens are rated for above. The
value always has a word beside it ("Busy", "Low", "Not sent") and the
health cards' glyph, so rule 1 holds. The thresholds are defined once,
with their sources, above `FIELD_FLAGS` in `app.js`. A value the node
did not send is never coloured: absent is not bad.

## 5. Categorical scale: packet families

The family ramp is the categorical scale. Charts that split by packet
type, the live map and the node page's "What it sent" chart all use
it, so one family has one colour everywhere. It holds seven entries:
six families and a bucket for everything else. Past seven, fold the
rest into the bucket rather than repeat a colour. Each family also has
a shape on the map (`FAMILIES` in `map-live.js`).

Ratios are against `--bg`. The floor is 3:1 for a mark.

| Token | Dark | Ratio | Light | Ratio |
| --- | --- | --- | --- | --- |
| `--pkt-position` | `#f4703f` | 6.5 | `#cf5220` | 3.9 |
| `--pkt-nodeinfo` | `#a48fd0` | 6.7 | `#7457ad` | 5.1 |
| `--pkt-telemetry` | `#46b3e6` | 7.9 | `#1b77a5` | 4.5 |
| `--pkt-text` | `#f6ece2` | 16.2 | `#25190f` | 15.4 |
| `--pkt-trace` | `#b6d94c` | 11.7 | `#5a8410` | 4.0 |
| `--pkt-routing` | `#b59c88` | 7.2 | `#7d6857` | 4.7 |
| `--pkt-other` | `#7d6857` | 3.6 | `#978573` | 3.2 |

## 6. Node roles

A role is what a node is. A family is what a packet was. The two are
drawn in the same frame, so they are separate groups and must not
share values. Routers and repeaters are greens and teals, clients are
yellows, blues and purples, the TAK family is pinks.

| Token | Dark | Ratio | Light | Ratio |
| --- | --- | --- | --- | --- |
| `--role-ROUTER` | `#8cb369` | 7.9 | `#4a8a2a` | 3.8 |
| `--role-ROUTER_LATE` | `#4fa3a5` | 6.4 | `#2b7a7c` | 4.5 |
| `--role-ROUTER_CLIENT` | `#b6d94c` | 11.7 | `#6a9612` | 3.2 |
| `--role-REPEATER` | `#2e8b7a` | 4.6 | `#1c6b5d` | 5.7 |
| `--role-CLIENT` | `#edc04b` | 11.0 | `#9c7600` | 3.8 |
| `--role-CLIENT_MUTE` | `#a48fd0` | 6.7 | `#7457ad` | 5.1 |
| `--role-CLIENT_BASE` | `#6fa8dc` | 7.5 | `#2d6aa8` | 5.0 |
| `--role-CLIENT_HIDDEN` | `#8d7a66` | 4.6 | `#7d6857` | 4.7 |
| `--role-CLIENT_TAK` | `#e06c9f` | 6.1 | `#b0417a` | 4.9 |
| `--role-TAK_TRACKER` | `#d94f70` | 4.8 | `#a83656` | 5.7 |
| `--role-TAK_PLUGIN` | `#b07cc6` | 5.9 | `#8551a1` | 5.1 |
| `--role-ATAK_PLUGIN` | `#c98bdb` | 7.4 | `#955aab` | 4.4 |
| `--role-TRACKER` | `#f4a259` | 9.1 | `#bd6418` | 3.8 |
| `--role-SENSOR` | `#46b3e6` | 7.9 | `#1b77a5` | 4.5 |
| `--role-LOST_AND_FOUND` | `#ef6f5c` | 6.4 | `#b7352a` | 5.3 |

## 7. The theme switch

- The choice is `system`, `dark` or `light`, kept in `localStorage`
  under `sonoran.theme`. The default is `system`.
- A short script at the top of `index.html` sets `data-theme` on
  `<html>` before anything paints. It always sets `light` or `dark`,
  so the CSS holds one block of light values.
- `html`, `body` and `<meta name="theme-color">` all carry `--bg` in
  both themes (#253). On an iPad an overscroll past the top shows what
  lies behind the document and Safari tints its bars with
  `theme-color`, so any of the three that differs shows as a band. The
  pre-paint script sets `theme-color` for the chosen theme and
  `applyTheme` sets it again on a switch.
  `tests/unit/test_overscroll_background.py` pins all three.
- Charts and map layers read the palette once at load. A change of
  theme reloads the page, so nothing keeps an old colour.
- The basemap is a light tile set inverted for the dark theme. The
  light theme shows the tiles as they come.
- The public coverage embed stays dark. It is framed on other people's
  pages, and following the host page's scheme is still open.

## 7.5 Controls: pressed, hover, disabled

A toggle's state must be readable **without colour** and **without
pointing at it**. Two failures made the old rule untrustworthy:

- On was an accent border and accent text; off was a line border and
  cream text. Colour was the only difference, against rule 1.
- `button:hover` set the *same* accent border, so hovering an off
  button to read it made it look on. The act of checking changed the
  answer.

So the chosen state is **filled**, following what `.coverage-layers`
already did. A fill is legible at a glance and cannot be produced by
hovering.

| State | Surface | Ink | Extra |
|---|---|---|---|
| pressed | `--toggle-fill` (default `--accent`) | `--on-accent` | `✓` and 600 weight |
| not pressed | `--panel` | `--text` | — |
| not pressed, hover | `--panel-2` | `--text` | border `--accent-soft`, **never** `--accent` |
| pressed, hover | `--toggle-fill` | `--on-accent` | unchanged |
| disabled | unchanged | unchanged | `opacity: .5`, `cursor: not-allowed`, no hover |

Measured on the live dashboard, label against its own surface:

| | dark | light |
|---|---|---|
| pressed (`--on-accent` on `--accent`) | **6.40** | **5.27** |
| not pressed (`--text` on `--panel`) | **13.21** | **14.27** |

Both clear the 4.5 floor. The old pressed state measured **4.38 in the
light theme**, below it, because it put `--accent` text on `--panel-2`.

`--toggle-fill` is a per-control variable, so a group can take a
different colour without a new rule. The Live control uses
`--status-ok`, because it reports whether the page is running and
green already means running in the sidebar dot.

The `✓` is `content: "✓" / ""`. Generated content **is** announced by
screen readers — it is not decorative by default — and `aria-pressed`
already carries the state, so the empty alternative text stops the
control reading as "tick Traffic, pressed".

## 8. Checking contrast

The figures above use the WCAG 2.2 relative luminance formula. To
check a pair:

```python
def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

def ratio(a, b):
    return (max(lum(a), lum(b)) + 0.05) / (min(lum(a), lum(b)) + 0.05)
```

`tests/unit/test_palette.py` checks the floors in sections 3 to 5 for
both themes.
