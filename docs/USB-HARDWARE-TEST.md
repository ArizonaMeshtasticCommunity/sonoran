# Hand-testing the USB config path

**Corrected 2026-09-24.** This file used to open by saying most of the
work was verified against real firmware. It was not verified enough: a
hardware test found that the write zeroed every setting it did not
change, because the run it called "verified" re-read only the field it
had changed and the fields it had protected. See "Results so far"
below, and take the re-read instruction there seriously — it is the
difference between the two runs.

**Much of this is verified against real Meshtastic firmware.**
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

## Results so far

### T-Echo (nRF52, USB 239a:4405), firmware 2.7.26.54e0d8d — 2026-09-23

**Read: pass.** Open to "Done" in about 400 ms. 16,378 bytes in **439
reads of 1 to 108 bytes**, split at arbitrary points; 128 of them were
exactly 64 bytes, the nRF52 packet size. The decoder reassembled all of
them. The port was released afterwards and `meshtastic --port … --get`
opened it immediately, twice. The check agreed with
`meshtastic --export-config`.

**Write: pass, after a fix.** Four frames in about 2 ms, node rebooted
13.7 s later, back on the same port 0.9 s after that. A full
`--export-config` diff before and after showed **only** the two
intended changes. The keys, admin key, PSKs, bluetooth, MQTT and region
were untouched.

**Not tested:** an unplug during the read (it is too fast to pull the
cable by hand), and the **ESP32 half, which is still to do.**

### The bug that test found, and what it means for how you test

The write **zeroed every setting it did not change.** The firmware
*replaces* a config section with what it is sent
(`config.lora = validatedLora` in `AdminModule.cpp`), and the page sent
only the changed fields. A "change hopLimit" write would have set
`region` UNSET and `txEnabled` false — stopping the radio — and any
write touching the security section would have sent empty `adminKey`,
`privateKey` and `publicKey`, which is the lockout this feature exists
to prevent. Fixed in #201: each section is now sent whole, and a section
that was not read is refused rather than zeroed.

**The meshtasticd run did not catch it, and the reason is the important
part.** That run re-read `hopLimit` and the protected fields — the field
that was changed, and the fields explicitly guarded. It did not re-read
the *rest* of the lora section. Every field it checked was a field
somebody was already thinking about.

> **So: after a write, re-read the WHOLE section and diff it, not the
> field you changed.** `meshtastic --export-config` before and after is
> the check that finds this class of bug; a targeted re-read is the
> check that misses it.

**That check has now been run, and the fix holds.**
`tools/firmware-write-check/` drives the shipped `serial-write.js`
against meshtasticd over TCP and then diffs a whole
`--export-config`. Changing `lora.hopLimit` 3 → 5: **43 fields
compared, 3 changed** — `hopLimit` itself, `channel_url` (which
encodes LoRa settings), and `codingRate` absent → 5, which the
firmware recomputed from `usePreset`. **Nothing was lost**, and
`txEnabled` and `region` both survived; those are the two the old code
destroyed.

The detector is held to its job by `tests/unit/test_firmware_write_diff.py`,
including the failing state: fed a config with the lora section zeroed,
it must name `txEnabled` as lost. A comparison only ever seen passing is
not evidence that it can fail.

So what is left for a board is the **USB transport specifically** —
meshtasticd speaks the same client API but it is not a serial port. The
protocol and payload questions are answered.

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
