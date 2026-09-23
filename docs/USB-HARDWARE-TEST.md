# Hand-testing the USB config path

**Most of this is already verified against real Meshtastic firmware.**
`meshtasticd` 2.7.26 runs the actual firmware and speaks the same
client API over TCP, so the protocol half was testable without a board
after all — and it found a bug that every simulator missed.

What is left needs a board, and it is **narrower than it looks**: the
USB transport only.

## What is already proven, so you do not re-test it

Against `meshtasticd` 2.7.26, not a mock:

- **Read.** All 8 config sections, all 8 channels, real `my_info` and
  `metadata` (firmware `2.7.26.54e0d8d`), reassembled from whatever
  chunk sizes the firmware and TCP produced.
- **Write.** Read → plan → write → re-read. `lora.hopLimit` 3 → 5
  applied; `security.isManaged` and `bluetooth.enabled` **refused, and
  the firmware confirms neither changed.**

That second line is #117's whole safety contract, checked against the
thing it has to talk to.

### The bug that only real firmware caught

An `AdminMessage` sent on its own is **accepted by the firmware and
does nothing.** It has to be wrapped in a `MeshPacket` addressed to the
local node on the admin port. Before the fix the write reported
`wrote 1` and a re-read showed the old value, with no error anywhere —
and all 22 unit tests passed, because a simulator checks what we
*send*, not what a node *does* with it.

Worth knowing when you test: **"it said it worked" is not evidence
here.** Always re-read.

## What still needs a board, and why

The USB transport layer, which TCP cannot stand in for:

1. **How a CDC-ACM driver chunks reads.** The decoder handles one byte
   at a time and whole frames; a real driver may do something between.
2. **What happens across the reboot** a `commit_edit_settings`
   triggers — whether the port disappears cleanly or hangs.
3. **Whether the port is released** afterwards, so the Meshtastic app
   and CLI can open it again.
4. **nRF52 versus ESP32.** Different USB stacks; this is why both
   issues ask for one of each.

## What you need

- A board on USB. Both issues ask for **one ESP32** (Heltec V3,
  Station G2) **and one nRF52** (RAK4631, T-Echo), because they use
  different USB stacks.
- Chrome or Edge on a desktop. Web Serial exists nowhere else.
- The page over **https** or on `localhost`. Web Serial needs a secure
  context; on a remote host, a private network address will not do.

## Part 1 — read (#116)

1. Open `#config` and find **Connect a node by USB**.
2. Click it and pick the port. Record what the progress line says.
3. When it finishes, the page should show the check for that node.

Record:

- [ ] The board and firmware version.
- [ ] Did the config arrive? How long did it take?
- [ ] Does the check match what `meshtastic --export-config` for the
      same node gives, loaded as a file? The two paths must agree.
      (Verified against meshtasticd already; this confirms it over
      USB.)
- [ ] Unplug the board mid-read. Does the page say something useful,
      or does it hang?
- [ ] After a read, can the Meshtastic app or CLI still open the port?
      If not, the port was left open and that is a bug.

## Part 2 — write (#117)

**Use a board you are willing to reset.**

1. Read the node as above. The change preview should list every
   difference, "current → new".
2. Check the preview against `meshtastic --get` for two or three of
   those settings. They must agree.
3. Leave **Download a backup** ticked. Confirm the write.
4. When the node reboots, connect again and read it.

Record:

- [ ] Did every ticked change take effect? **Re-read to check — the
      write reporting success is not evidence, as the bug above
      showed.**
- [ ] Did anything change that you did **not** tick?
- [ ] Were the security settings left alone? Check `admin_key`,
      `is_managed`, the channel PSK and `bluetooth.enabled` with
      `meshtastic --get`. **The page must not have touched any of
      them.** This is the one that can lock somebody out of their node.
- [ ] Did the backup file load back onto the node with
      `meshtastic --configure`?
- [ ] How long was the reboot, and did the page recover?

## If something fails

The page has a **Copy diagnostic report** button on failure (#119). It
contains no config contents, no channel names, no keys and not even the
file name — paste it into the issue as it is.

## What to write in the issue

The board, the firmware version, what worked, and anything that did
not. A failure here is more useful than a pass: it is the only
information no test in this repo can produce.
