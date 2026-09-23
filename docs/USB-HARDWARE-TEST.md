# Hand-testing the USB config path

Everything in #116 and #117 is built and verified against a simulated
node. **This is the one step that needs a physical board**, and it is
the only thing standing between those issues and closed.

It takes about ten minutes. Paste the results into #116 and #117.

## Why a simulator was not enough

The simulator proves the *conversation*: the right frames go out, the
reply is reassembled from any chunk boundary, log text is ignored, a
silent node times out, the port is closed on every path, and the
dangerous settings are refused.

It cannot reproduce what a real port does — how the driver splits
reads, how fast a board answers, whether a reboot drops the port
cleanly, and what an nRF52 does that an ESP32 does not. **Those are
exactly the things that break in the field**, which is why both issues
ask for a hand-test rather than accepting a green suite.

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
      same node gives, loaded as a file? **This is the real test** —
      the USB path and the file path must agree.
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

- [ ] Did every ticked change take effect?
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
