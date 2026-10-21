# NEWCOMER.md — Write every screen for a Meshtastic newcomer

This guide tells you how to make a change that a person in their first
weeks of Meshtastic can understand. It is for people and for AI agents.
It uses ASD-STE100 Simplified Technical English (`AGENTS.md` §3).

The rule itself is `AGENTS.md` §3B. This file gives the reasons, the
patterns, and the review that checks them.

## 1. Who the reader is

Write for this person:

- They have one or two nodes. They set them up with the phone app.
- They know what a **node** is, what a **message** is, and that the mesh
  passes messages from node to node.
- They do not know what **SNR**, **RSSI**, a **hop limit**, a **modem
  preset**, a **gateway**, **MQTT**, a **role** or a **traceroute** is.
- They often use a phone. A phone has no hover, and the screen is
  360 px wide or less.
- They came with a question: "Can people hear me?", "Is my node
  working?", "Where does the mesh reach?", "Where should I put my
  node?"

The maintainers and their agents are experts. That is the risk: a word
that is plain to an expert is a wall to this reader. Read your screen as
the reader, not as yourself.

## 2. The requirements

Each change to the user interface must meet all of these.

1. **A plain label.** The words on the control say what it does for the
   reader. Use the reader's words, not the protocol's words.
2. **Each technical word has its tooltip from the glossary.** Put
   `data-term="<id>"` on the element that holds the word. The words and
   their explanations are in `src/sonoran/web/static/glossary.js`. Do
   not write a second explanation of the same word somewhere else.
3. **Advanced settings are behind "Advanced".** The first view asks only
   for what a newcomer can answer. The planner is the model (§3.2).
4. **The defaults work.** A newcomer who changes nothing gets a correct,
   useful result.
5. **An empty state or an error says what to do next.** "No data" is not
   enough. Say why there is nothing, and what the reader can do.
6. **Units have words.** Write "15 min", "3 hops", "-110 dBm". Never a
   bare number.
7. **No internal names in primary text.** Show `Router late`, not
   `ROUTER_LATE`. Keep the exact value in the tooltip (§3.6).
8. **A phone works.** Check the screen at 360 px wide. Every tooltip
   opens by a tap, and closes on Escape or a tap outside.

`tests/unit/test_newcomer_glossary.py` checks requirement 2 and part of
requirement 7 on every test run (§6). A person or an agent checks the
rest with the review in §5.

## 3. Patterns, with examples from Sonoran

### 3.1 A plain label with a glossary tooltip

Write the plain word, and mark it with its glossary id:

```html
<button type="button" class="toggle" data-show-traces data-term="traceroute">Live traceroutes</button>
```

In a script, a table column takes `term`, and any element takes
`'data-term'`:

```js
{ label: 'SNR', term: 'snr', num: true, cell: (row) => snrCell(row.snr) },
el('h3', { 'data-term': 'direct snr' }, 'Direct link signal over time'),
```

`revealHints` in `app.js` adds a small "i" button. The button opens the
glossary text in the same popover that the column hints use. One element
can name more than one term, separated by spaces.

Where the button goes:

- Inside the element, after its text, for a heading, a paragraph or a
  span.
- Beside the element, for a control such as a `<button>` (a button
  cannot hold a button), and for an element that has an `id` (another
  control can take its name from that element).
- Inside a `<label>`. The control first gets its current name as an
  `aria-label`, so the words of the button do not join its name.

On a heading, a table column, a field or a tile that also has a
`data-hint`, the glossary text goes into the same panel as the hint. A
heading never gets two buttons.

### 3.2 Simple and Advanced, as in the planner

The planner opens in **Simple**. It asks for the site, the antenna
heights, the preset and three pickers: your radio, your antennas, your
cable. Every other field is in **Advanced** (`docs/PLANNER.md`, "Simple
and Advanced").

Copy these parts of it:

- Simple is the default for a first visit.
- Advanced hides nothing from the result. Simple hides fields with CSS
  (`data-advanced-only`), and every value is still read and used.
- A picker in Simple ("Select your radio") fills the numbers that
  Advanced shows as boxes.

### 3.3 Defaults that work

The coverage settings open on the infrastructure map with all usable
ground shown ("0 dB: all usable ground"). A newcomer who opens the page
and changes nothing sees the correct map. "Reset to default" brings that view back.

### 3.4 Explain an empty state

The map says "No node was heard on Short Turbo" when a preset has no
traffic. It does not show an empty map with no words. Do the same: name
what is missing, and give the reason when it is known.

### 3.5 Units with words

The traffic window says "15 min" and "1 h". The coverage scale says
"dBm" beside each number. `units.js` turns distances and heights into
the reader's units. Use it, and never print a bare number.

### 3.6 A plain name first, the internal name in the tooltip

`labels.js` holds the plain name of every role and packet type. The node
page shows "Router late". The field's tooltip says what the role does,
and gives the exact value `ROUTER_LATE` for a person who needs it. Do
the same for any enum value.

## 4. Jargon and plain words

Use the plain words in labels and sentences. Keep the technical word
where the reader will meet it in the Meshtastic app, and give it its
tooltip. `docs/GLOSSARY.md` has the full list of explained words.

| Technical word | Plain words for a label | Glossary id |
|---|---|---|
| SNR | Signal quality, how clear the signal was | `snr` |
| RSSI | Signal strength | `rssi` |
| dBm | Signal power (keep "dBm" as the unit) | `dbm` |
| Hop | One relay | `hop` |
| Hop limit | How many relays are allowed | `hop-limit` |
| Modem preset | Preset, radio settings (LongFast, MediumFast) | `modem-preset` |
| Gateway, MQTT uplink | A node that sends what it hears to the internet | `gateway` |
| Upload | One copy a gateway sent to the server | `upload` |
| Channel utilization | How busy the air is | `channel-utilization` |
| Airtime, TX utilization | How much this node sends | `airtime` |
| Portnum | Packet type | `packet-type` |
| Neighbor info | Nodes it hears directly | `neighbor-info` |
| Traceroute | Route test | `traceroute` |
| Position precision | How exactly a position is shared | `position-precision` |
| Coverage prediction | Where the signal should reach (an estimate) | `coverage-prediction` |
| PKI | Private direct message | `pki` |
| `ROUTER_LATE` and other enums | The name in `labels.js` | `role-router-late` and the other `role-` ids |

## 5. The newcomer review

Run this review on every pull request that changes what a reader sees.
A person or an AI reviewer can run it. Put the result in the PR, under
"Newcomer check".

Act as this reader: "I set up my first node last week with the phone
app. I know what a node and a message are. I do not know what SNR, a
hop or a preset is. I am on my phone." Open each screen that the PR
changes, at 360 px wide, and answer these questions:

1. What is this screen for? Can I say it in one sentence after five
   seconds?
2. Which words on the screen do I not know? Does each one have an "i"
   button? Does the explanation use only words I know?
3. Which number do I not understand? Does each one have a unit in words?
4. Which control would I be afraid to touch? Is it behind "Advanced", or
   does it say what it changes?
5. If I change nothing, is the result correct and useful?
6. If the screen is empty or shows an error, do I know what to do next?
7. Do I see an internal name, such as `ROUTER_LATE`, `portnum` or a
   database column name?
8. Can I open and close every explanation with one finger? Does any
   panel run off the side of the screen?

For each "no", write the screen, the words, and the fix. For an AI
reviewer, give it this section, the diff and screenshots at 360 px and
at desktop width, and ask for a table of findings with a fix for each.

## 6. The automatic check

`tests/unit/test_newcomer_glossary.py` runs with `pytest`, so CI runs
it with no extra job. `tools/newcomer_check.py` does the work. It checks
these things:

- Each glossary entry has a label and a plain explanation of at most
  three sentences and 320 characters. A "learn more" link goes to
  `meshtastic.org` or to the Meshtastic GitHub only.
- Each `data-term` and `term:` in the interface names an entry that
  exists.
- `docs/GLOSSARY.md` is the same as `glossary.js`.
- New on-screen text that uses a glossary word has its tooltip. New text
  that shows an internal name such as `ROUTER_LATE` is reported too.

### 6.1 What it reads

- `index.html` and `embed-coverage.html`: each text node and each
  `<option>`. It skips comments, `<script>`, `<style>`, `<template>`,
  `<svg>`, `<code>` and `.sr-only` text.
- The interface scripts in `web/static/`: a quoted string given to
  `label:` or `text:`, and the text of `el('h3', {...}, '...')` for a
  heading, a table heading, a term, a legend, a label, a summary, a
  button, a paragraph, a span, a list item or a strong.
- A text is covered when its element, or a parent up to the nearest
  block such as a `div` or a `section`, has `data-term` with the id. In
  a script, the object that holds the string must have `term: '<id>'`
  or `'data-term': '<id>'`.
- Which words count is the `words` list of each glossary entry. A word
  that is too common to mark at every use, such as "channel" or
  "packet", has an empty list. Mark its first use in a panel by hand.

### 6.2 What it cannot see

- Text built at run time: template strings (`${...}`), strings joined
  with `+`, and strings that a function returns.
- Attributes: `placeholder`, `aria-label` and `title`.
- `labels.js` and other name tables. The code that draws a name carries
  its term.
- Whether a tooltip is useful. Only the review in §5 can say that.

### 6.3 The baseline only gets shorter

`tests/unit/newcomer_baseline.json` lists the places that used a
glossary word without its tooltip when this rule came in. On that day
`main` had 130 such places, and this change fixed 42 of them.

- **A new place fails the test.** The message says which text, which
  term, and what to add.
- **A fixed place fails the test until you remove its line.** Run
  `uv run python -m tools.newcomer_check --prune`. So the list can only
  get shorter.
- **The tool does not add lines.** `--write-baseline` refuses to add a
  line unless you also give `--allow-growth`. Use that only when the
  word really is not the technical sense on that screen, say why in the
  PR, and get a maintainer's agreement there.

### 6.4 How to change the rule

The rule belongs to the maintainers (Logan and Tyler). To change it:

- **A word or its explanation:** edit `glossary.js`, then run
  `uv run python -m tools.newcomer_check --write-doc`.
- **Which spellings count:** edit the `words` list of the entry.
- **What the check reads:** edit `tools/newcomer_check.py` and its tests,
  then update §6.1 and §6.2 here.
- **The rule itself:** edit `AGENTS.md` §3B and this file in the same
  pull request.
