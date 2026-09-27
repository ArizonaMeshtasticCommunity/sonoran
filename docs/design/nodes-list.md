# The nodes list: sorting, filtering, and honest counts

Design, 2026-09-19. Approved approach: typed controls, server-side
sorting, state in the URL. A query language and a generic filter
builder were both considered and rejected; see section 9.

## 1. What is wrong with it today

`/api/nodes` takes `q`, `hw`, `role`, `gateway`, `active_hours`,
`before` and `limit`. It always orders by `last_heard DESC` and caps at
500. The page asks for a page of rows and prints

    `${count(rows.length)} nodes match.`

Production holds 2,372 nodes. So the page says **"300 nodes match"**
when it means **"here are 300"**. That is the same fault
`/api/map/traffic` already corrected for itself, in its own words:

> Counting the returned rows instead reported the cap: a busy mesh
> fills it in a couple of minutes, so every longer window answered with
> the same number and the window picker looked broken.

It is worse on a sortable table than on an unsorted one, which is why
it has to be fixed first.

## 2. Sorting server-side is not an optimisation

It is the difference between a true answer and a false one.

The list is capped. Sorting the rows the browser happens to hold sorts
**the 500 most recently heard nodes by name** and presents the result
as **the first 500 nodes by name**. Those are different sets, and a
reader cannot tell them apart by looking.

So `sort` and `order` are query parameters, the database orders the
whole matching set, and the browser never reorders rows it was given.

## 3. The API

### 3.1 Ordering

| Parameter | Values | Default |
|---|---|---|
| `sort` | `last_heard`, `first_seen`, `name`, `node_id`, `hw`, `role`, `channel`, `position` | `last_heard` |
| `order` | `asc`, `desc` | `desc` |

Every sort is made total by appending `node_num` as a tie-break.
Without it a node can appear on two pages, or on neither, because
Postgres is free to order equal rows differently between queries — and
with 160 nodes reporting no role, ties are the normal case here, not an
edge.

Nulls sort last in both directions. A node with no role is not the
"smallest" role, and a reader scanning for roles wants them out of the
way whichever direction they clicked.

`name` orders by `lower(coalesce(long_name, short_name, node_id))`, so
the order matches what the column actually shows.

### 3.2 Filters, added

| Parameter | Values | Reads |
|---|---|---|
| `channel` | exact name | `node.last_channel` |
| `position` | `exact`, `coarse`, `none` | `last_position_precision_bits` and the lat/lon |
| `licensed` | bool | `node.is_licensed` |
| `first_seen_hours` | 1..8760 | `node.first_seen` — "new nodes" |
| `quiet_hours` | 1..8760 | `node.last_heard` — "gone quiet" |
| `gaps` | `bad`, `unknown`, `ok` | the gaps artefact, and requires `gaps_preset` |

`quiet_hours` was added on 2026-09-26 for §6.2 of the UX overhaul, whose
ask is that everything sortable becomes filterable. It was the one
sortable column filterable in one direction only: `active_hours` asks
"heard since", and nothing asked "not heard since" — which is the
question "which routers have gone quiet" actually is, and the only way to
ask it was to widen the window to *any time*, sort ascending and read
from the top.

`before` can express it and would put the clock in the caller's hands: a
browser whose clock is wrong would then filter on the wrong hour, with
nothing on the page saying so. `active_hours` already has the server name
"now", and a band built from one of each — "heard this week but not
today" — has to be measured against one clock, not two.

The existing `q`, `hw`, `role`, `gateway`, `active_hours`, `before` and
`limit` are unchanged.

`offset` is added for paging, bounded like `limit`.

### 3.3 The honest total

`/api/nodes` **keeps returning a bare JSON array.** It is documented as
public in `docs/API.md` 3.1 and something outside this repo may read it.

The count of everything matching the filters travels in an
**`X-Total-Count`** header. `node` is a plain table of a few thousand
rows, not a hypertable, so counting it is cheap — unlike the counts
`/api/stats` had to start caching.

The browser gets one helper, `getList`, returning `{ rows, total }`.

### 3.4 `gaps` needs a preset, and that is not a nuisance

A node can need help on MediumFast and be fine on LongFast. They are
different meshes: a node on one cannot hear a node on the other.

`AGENTS.md` 9.7 forbids merging presets everywhere else in this
product, and "needs help on any preset" would be exactly that merge
wearing a filter's clothes. So `gaps` without `gaps_preset` is a 422
naming the missing parameter, and the column shows the state **for the
preset that was asked about**.

The filter reads the artefact the gaps job already writes, through the
same store the gaps routes use. It does not query the database for it
and it does not recompute anything. When no assessment has been
written, the filter is offered but disabled, with a sentence saying the
job has not run — the same shape the coverage page uses for "no run
published".

## 4. The page

### 4.1 Sortable headings

Every column heading becomes a button: unsorted, ascending, descending.
`aria-sort` on the `th`, an arrow that is not the only signal, and the
sort in the URL.

Two columns need care rather than a rule:

- **Flags** is not one value. It sorts by gateway first, then position,
  which is a decision and is written in the column's hint.
- **Last heard** shows "10s ago" and sorts by the timestamp behind it,
  descending first, because "most recent first" is what a reader means
  by clicking it once.

### 4.2 Filters

The existing controls stay where they are. New ones join them, and the
whole bar collapses into a disclosure once more than three filters are
set, so the common case stays a search box and two pickers.

### 4.3 Starting points

Filters nobody finds are filters nobody has. Three chips above the
table, each one setting a complete query:

- **Silent routers** — role in the repeating set, not heard in 7 days
- **No position** — `position=none`, which is the worklist for issue #3
  item 1 and for the 75 coarse nodes that the siting half cannot see
- **Needs help** — `gaps=bad` on the preset the page is showing

### 4.4 Saying what is on screen

    2,372 nodes · showing 300 · sorted by name · 4 filters

Never "300 nodes match". When the total exceeds what is shown, a
**Show more** control fetches the next page and appends, the same
idiom the message and neighbour lists already use.

### 4.5 The URL carries the query

`#nodes?sort=name&order=asc&role=ROUTER&position=none`

So a query can be pasted into a chat message, and the back button
undoes a filter. Fragments never reach a `Referer` (9.9.1), which is
why the query goes there rather than into a search string.

## 5. What this does not do

- **No free-text query language.** A parser is a surface to get wrong,
  and a half-implemented one is worse: a reader cannot tell which parts
  are supported. The URL gives the shareability that made it tempting.
- **No generic field/operator/value builder.** Maximum power, heaviest
  UI, and most operators would never open it.
- **No client-side reordering**, ever. See section 2.
- **No new computation.** Every filter reads something already stored
  or already written by a job.

## 6. Testing

- Unit: the sort whitelist rejects anything not on it; `name` collates
  as the column displays; nulls sort last both ways; the tie-break
  makes every order total.
- Integration, against a real database: `X-Total-Count` is the count of
  matches and not of returned rows; paging with `offset` returns each
  node exactly once across pages and never repeats one at a boundary;
  `gaps` without `gaps_preset` is a 422; `position=none` returns only
  nodes with no usable position.
- A journey in `tools/dev/e2e.js`: sort by a column, assert the order
  actually changed and that the total did not.

## 7. Risks

- **A sort injection** is the obvious one. `sort` is matched against a
  fixed map to a column; nothing from the caller reaches the query.
- **`offset` paging drifts** if a node is heard between two pages.
  Acceptable here: the list is a view of a living mesh, and the
  alternative, a keyset cursor, is more machinery than a few thousand
  rows deserve. Said in `docs/API.md` rather than hidden.
