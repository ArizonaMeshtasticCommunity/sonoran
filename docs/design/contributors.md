# Contributors: jobs on members' own nodes (#178)

Issues: #178 (the system), #179 (the contributor service), #181
(contributor management), #182 (the display). Tyler wrote all four.
The transport is from Tyler's comment on #179. Logan chose it on
2026-10-14 because it adds no writable API to Sonoran.

## 1. Why

A node measures its own radio environment and keeps it in `LocalStats`.
`noise_floor` is the one value we want first. A node does not send
`LocalStats` over the mesh: it sends it to its own phone only
(`DeviceTelemetry.cpp`, `sendLocalStatsToPhone`). Any node answers a
**request** for it (`DeviceTelemetryModule::allocReply`, firmware
v2.7.26.54e0d8d, `src/modules/Telemetry/DeviceTelemetry.cpp` lines 87
to 89). The answer goes back to the node that asked, as a direct
message. Sonoran has no node on the mesh, so it cannot ask.

Whether the answer is encrypted with PKI, so that only the asking node
can read it, is not checked here. #178 says it is. The firmware uses
PKI for a direct message only when the sender has the receiver's
public key; otherwise it may use the channel key. This design does not
depend on it: the contributor reads the answer from its own node either
way.

A **contributor** is a member's own machine with a Meshtastic node it
can talk to. Sonoran gives it jobs. It does a job with its node and
sends the result back.

### 1.1 What this can tell us

- What one node measured about its own radio, at one time: its noise
  floor, channel use, transmit airtime, and its packet counters.

### 1.2 What it cannot tell us

- The measured noise floor of a node is **not** the theoretical floor
  in `sonoran/radio/presets.py` (`noise_floor_dbm`). The coverage map,
  gaps and calibration use the theoretical one. This work does not
  change them (rancur on #182). The page always says **measured noise
  floor** and never the bare words "noise floor".
- One reading is one moment. A node with a noisy neighbour that
  transmits now and then reads different values at different times.
- A node that no contributor hears gets no readings. A missing reading
  is "not measured", never "quiet".

## 2. Words

- **Contributor**: the service `sonoran-contributor`, and the machine
  that runs it. It is the RF agent's repository, renamed.
- **Location** and **source**: as for RF stations (#305). One source
  is one contributor, with one broker login, `rf-<location>-<source>`,
  minted by the registrar.
- **Target**: a node that Sonoran wants a reading from.
- **Job**: one request for one target, given to one contributor.
- **Round**: the jobs for one target in one interval. A round ends
  with a reading, or when every candidate has failed.

## 3. Topics

Everything is under `sonoran/v1/contributors/<location>/<source>/`:

| Topic | Who publishes | Retained | What |
|---|---|:-:|---|
| `outbox/<job>` | Sonoran | yes | A job. An empty message clears it. |
| `inbox/<job>` | the contributor | no | The result of that job. QoS 1. |
| `status` | the contributor | yes | The heartbeat, with the nodes its node hears. |

`<job>` is 32 lower-case hex characters.

The broker decides who may do what (the registrar writes the rules):

| Login | Subscribe | Publish |
|---|---|---|
| `rf-<location>-<source>` | its own `outbox/#` | its own `inbox/#` and `status` |
| Sonoran's dispatcher login | `.../+/+/inbox/#`, `.../+/+/status` | `.../+/+/outbox/#` |
| every other login | nothing under `sonoran/` | nothing under `sonoran/` |

Sonoran checks the topic again (§5.2). It never relies on the broker
alone. The topic tree is not under `msh/`, so no Meshtastic bridge
carries it.

## 4. The messages

The contract is `sonoran/contrib/schema.py`, exported as JSON Schema to
`docs/contributor-message-v1.schema.json`. The contributor repository
keeps a copy, as for `rf/v1`. Unknown fields are ignored.

- **Job**: `v`, `job`, `kind` (`local_stats` only, for now), `target`
  (`!` and 8 hex digits), `issued`, `expires`.
- **Result**: `v`, `job`, `location`, `source`, `kind`, `target`,
  `outcome` (`ok`, `no_reply`, `refused`, `error`), `sent`, and, with
  `ok`: `received` (when the answer reached the contributor's node)
  and `local_stats` (the protobuf fields, by their protobuf names).
  Optional: `hops`, `rx_snr`, `rx_rssi` of the answer, and `detail`,
  a short text for `error`.
- **Status**: `v`, `location`, `source`, `sent`, `version`,
  `mesh_node` (the contributor's own node, if it is connected),
  `kinds` (the job kinds it accepts), and `heard`: up to 250 nodes
  from its node's node list, with `node`, `hops` and `last_heard`.

250 is the largest node list a radio keeps (`MAX_NUM_NODES` on an
ESP32-S3 with 16 MB flash, `src/mesh/mesh-pb-constants.h` on the
firmware's default branch, 2026-10-14). A contributor with a longer
list sends the 250 most recently heard.

## 5. Sonoran

One new process, `sonoran-contrib` (compose profile `contrib`). It
holds the only broker login that can publish jobs. It runs as
`azmsh_jobs`, which can read `node.role`. The ingest role cannot, on
purpose (revision 0003), and gets nothing here.

**RF is not needed, on either side.**

- A contributor with mesh jobs only runs no SDR and sends nothing on
  `rf/v1/`.
- `sonoran-contrib` does not need `rf-ingest` (profile `rf`). The two
  share only the registrar's location and source ids.
- Without `rf-ingest`, the location's display name from the registry
  is not stored. The pages then show the location id as the "read by"
  name.

### 5.1 Which nodes, and how often

- Targets are the roles #178 names: `ROUTER`, `ROUTER_LATE` and
  `CLIENT_BASE`, from `node.role`.
- A target is due when it has no reading and no round for its
  interval. The interval is the firmware's own default telemetry
  interval for that role (`default_telemetry_broadcast_interval_secs`,
  `src/mesh/Default.h` line 18 at v2.7.26.54e0d8d, with `IF_ROUTER`
  at line 47): **12 hours** for `ROUTER` and `ROUTER_LATE`, **1 hour**
  for every other role. A router's makers chose 12 hours for its own
  telemetry to save airtime.
- **This limits rounds, not requests.** At most one round starts for a
  target in its interval. Inside a round, a failed job moves to the
  next candidate (5.2), so a target that does not answer can get one
  request from each candidate, about one every 5 minutes, in one round.
  There is no cap on candidates per round yet: a cap needs a number
  with a source (AGENTS.md 3A.2).
- **Airtime.** One job is one request and one answer. Each is relayed by
  the nodes between, so a target `n` hops away costs about `2n`
  transmissions or more, and a failed request can add a routing NAK.

### 5.2 Which contributor (#181)

1. The candidates are the contributors whose last heartbeat lists the
   target, heard within the target's interval.
2. A contributor that already failed this round is not a candidate.
3. A contributor with an open job is not a candidate. A contributor
   does one job at a time, so a contributor sends at most one request
   at a time. A reassignment waits for the next tick of
   `sonoran-contrib` (`CONTRIB_TICK_SECONDS`), and so does clearing a
   finished job's outbox message.
4. The best candidate has the fewest hops to the target. Unknown hops
   come last. Then the most recent `last_heard`.
5. No candidate: no job. The target waits for a heartbeat that lists
   it.

### 5.3 A job's life

1. Sonoran writes the job, then publishes it retained to the
   contributor's outbox.
2. The job expires 300 seconds after it is issued. 300 seconds is the
   Meshtastic Python library's own wait for an answer
   (`MeshInterface.__init__`, `timeout: int = 300`,
   `meshtastic/mesh_interface.py` line 93 at 2.7.11).
3. A result is accepted only if:
   - its topic names the location and source the job was given to,
   - and its body names the same,
   - and the job, target and kind match the job Sonoran wrote,
   - and the job has no result yet.
   A result that fails any of these is counted and dropped. So a
   contributor cannot write a reading for a node it was not asked
   about, or for another contributor's job.
4. `ok` stores one `local_stats` row and ends the round. Any other
   outcome, or no result before `expires`, fails the job. The next
   candidate gets a new job in the same round.
5. When a job is done or expired, Sonoran clears its outbox message.

A late result for an expired job is still accepted, if nothing else
in this list fails. The reading is real.

### 5.4 Tables (migration `i178`)

- `contrib_source`: one row per location and source: the last
  heartbeat (`sent`, `version`, `mesh_node`, `kinds`).
- `contrib_heard`: what each contributor's node hears. Replaced with
  each heartbeat.
- `contrib_job`: every job and its outcome.
- `local_stats`: a hypertable of readings: the target, the time, every
  `LocalStats` field, and which contributor measured it. Retention is
  `RETENTION_DAYS_METRIC`, as for `device_metrics`.

### 5.5 What it shows (#182)

- The node page: a **Local stats** family in
  `/api/nodes/{id}/telemetry?family=local_stats`, drawn as the other
  telemetry families are. The measured noise floor is in dBm.
- The RF tab: a **Measured noise floor** layer, the latest reading per
  node with a position, from `/api/rf/noise-floor`. Each point says
  when it was measured and by which contributor.

## 6. The contributor (#179)

- It talks to the member's own node over the Meshtastic TCP API, or a
  serial port.
- It does only the job kinds in its own allow list. It never sends an
  admin message, and never changes the node's settings.
- It does not set a hop limit. The node uses its own.
- It ignores a job whose `expires` has passed.
- It publishes a result for every job it starts, `no_reply` included.

## 7. Open points for Tyler

- Whether `CLIENT_BASE` uses the 1 hour interval, or the router one.
- Whether readings from a node's own phone link (a contributor that
  asks its **own** node) are wanted. Now they are allowed: the target
  can be the contributor's own node, with 0 hops.
