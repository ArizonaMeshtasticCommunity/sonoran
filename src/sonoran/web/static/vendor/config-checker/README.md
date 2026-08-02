# Arizona Meshtastic Config Checker

A client-side web application that validates Meshtastic node configurations against the Arizona Meshtastic Community recommendations. All processing happens locally in the browser -- **no data ever leaves your device**.

**Live site:** [cfgtest.azmsh.dev](https://cfgtest.azmsh.dev)

## Features

### Config Validation
Upload your Meshtastic config file and get an instant health report:
- LoRa radio settings (modem preset, frequency slot, OK to MQTT)
- Channel configuration and encryption status
- MQTT broker and topic settings
- Node role validation
- Broadcast interval recommendations (mobile vs. stationary)
- Firmware version check with update guidance

### Auto-Fix & Export
When issues are found, click **Auto-Fix & Export Config** to:
- Generate a corrected config with all AZ recommended values applied
- Download as a YAML file compatible with `meshtastic --import-config`
- Preserves your node name, role, and other personal settings

### Export Report
Download a text report of all check results for sharing or record-keeping.

### Privacy-Safe Diagnostics
If the tool hits an error (a parse failure, a serial glitch, etc.), a
**"Copy diagnostic report"** control appears. The report captures only
non-sensitive metadata to help the community debug the issue:
- error type and the operation/step that failed (parse / channel-url-decode / fixer / serial / firmware-check)
- tool version (release tag) and your browser + OS family
- the detected config *format* label, file *extension*, and file *size* in bytes
- a timestamp

It **never** contains your config contents, channel names, PSK/keys, MQTT
credentials, QR/URL input, your filename, or any setting values. The report is
built from a fixed whitelist of fields (see `js/diagnostics.js`), error messages
are scrubbed of any embedded payload, and **nothing is sent anywhere** -- it
stays in your browser until you choose to copy and share it. A regression test
(`tests/diagnostics-suite.mjs`) asserts that no input data can leak into a report.

### Web Serial (Beta)
Connect directly to your Meshtastic node via USB from Chrome or Edge:
- **Read Config** -- Pull current settings from the device
- **Apply Recommended Settings** -- Send AZ recommended values directly to the node
- Requires Chrome or Edge desktop browser (Web Serial API)

### Supported Config Formats

| Format | Source | Extension |
|--------|--------|-----------|
| Protocol Buffers (binary) | Android app export | `.cfg` |
| YAML | CLI `meshtastic --export-config` | `.yaml`, `.yml` |
| JSON | iOS app, Web client | `.json` |

All three formats are fully supported. The parser auto-detects the format from the file extension or content.

Android `.cfg` exports carry their channels in the Meshtastic shareable
`channel_url` (the `DeviceProfile` protobuf has no `channels` field). The
checker decodes that URL on import and re-encodes it on export, so channel
names, keys, and uplink/downlink flags survive an auto-fix round-trip.

## How to Use

1. **Select your region** -- Greater Phoenix/Tucson Metro or Rural Arizona
2. **Select your node type** -- Stationary (rooftop) or Mobile (handheld/vehicle)
3. **Upload your config** -- Drag and drop or click to browse
4. **Review results** -- See what's correct, what needs to change, and why
5. **Fix issues** -- Use the auto-fix export or follow the step-by-step instructions

### Exporting Your Config

**Android:** Open the Meshtastic app > Settings (gear icon) > Export Config (saves a `.cfg` file)

**CLI:** Run `meshtastic --export-config > my-config.yaml`

**iOS/Web:** Export from the app settings (saves a `.json` file)

## Checks Performed

### Firmware Version
- Checks against the latest stable Meshtastic release
- Links to the web flasher if an update is available

### LoRa Radio Settings
- **Modem Preset** -- Metro: Medium-Fast / Rural: Long-Fast
- **Frequency Slot** -- Metro: 18 / Rural: 20
- **Use Preset** -- Should be enabled
- **Frequency Override** -- Should be disabled
- **OK to MQTT** -- Should be enabled

### Channel Configuration
- Primary channel name
- Encryption key presence (warns on default key)

### MQTT Configuration
- MQTT module enabled
- Server, username, and password match the AZ community public broker config. The
  checker verifies these by **hash**, not by storing them in plaintext: it
  hashes the values from your config and compares against SHA-256 hashes in
  `js/constants.js`. This keeps the credentials out of the client source (bots /
  scrapers can't lift them) while still telling you whether your node is set up
  correctly. The actual credentials are distributed in the AZ Meshtastic Discord
  (`#getting-started`) and on [azmsh.net](https://azmsh.net).
- Topic format: `msh/US/AZ/{CityOrArea}`
- Uplink: ON / Downlink: OFF
- Map reporting

### Node Role
- CLIENT (rooftop home nodes)
- CLIENT_MUTE (mobile nodes)
- ROUTER (mountain-top / high-elevation)
- ROUTER_LATE (experimental rooftop installs)

### Broadcast Intervals
Separate recommendations for mobile vs. stationary nodes:

| Setting | Mobile | Stationary |
|---------|--------|-----------|
| Node Info Broadcast | 43200 (12h) | 43200 (12h) |
| Smart Broadcast | ON (100m, 60s) | OFF |
| Position Broadcast | 3600 (1h) | 43200 (12h) |
| GPS Update | 300 (5min) | 21600 (6h) |
| Device Metrics | 3600 (1h) | 3600 (1h) |
| Map Report | 3600 (1h) | 21600 (6h) |

## Privacy

**All config processing happens 100% in your browser.** Config files may contain private keys and are never uploaded to any server. The app works offline after the initial page load.

## Discord Bot Integration

Want a `/configcheck` slash command in your Discord server? See [docs/discord-bot-integration.md](docs/discord-bot-integration.md) for a complete setup guide with example bot code.

## Deployment

This is a fully static site. No server, no build step, no dependencies to install.

### Static Hosting (Cloudflare Pages, Netlify, GitHub Pages, etc.)

1. Clone the repo
2. Point your static host at the repository root
3. Set up your DNS to point your hostname (the community deploy is `cfgtest.azmsh.dev`) to the host

### Local Development

Just open `index.html` in a browser, or use any static file server:

```bash
python3 -m http.server 8080
npx serve .
```

## Tech Stack

- Pure HTML/CSS/JavaScript (no framework, no build step)
- [protobuf.js](https://github.com/protobufjs/protobuf.js/) for binary `.cfg` parsing
- [js-yaml](https://github.com/nodeca/js-yaml) for CLI YAML export parsing
- [Web Serial API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Serial_API) for USB device connection (Chrome/Edge)
- Third-party libraries are **self-hosted** in `js/vendor/` (pinned exact versions
  with Subresource Integrity), not loaded from a CDN — a floating CDN tag plus SRI
  breaks the moment upstream republishes a patch. To update, re-vendor the exact
  file and recompute its `integrity` hash.

## File Structure

```
/
├── index.html              # Main page
├── css/
│   └── style.css           # Styles (dark theme, desert palette)
├── js/
│   ├── app.js              # UI logic, file handling, Web Serial, report export
│   ├── parser.js           # Config file parser (protobuf, YAML, JSON)
│   ├── checker.js          # Validation engine (AZ recommendations)
│   ├── fixer.js            # Auto-fix engine and YAML export
│   ├── protobuf/
│   │   └── meshtastic-proto.js  # Protobuf schema definitions
│   └── vendor/             # Self-hosted, pinned third-party libs (SRI-guarded)
│       ├── protobuf.min.js     # protobuf.js 7.6.3
│       └── js-yaml.min.js      # js-yaml 4.2.0
├── docs/
│   └── discord-bot-integration.md  # Discord bot setup guide
├── README.md
└── .github/
    ├── ISSUE_TEMPLATE/
    │   └── config-check-issue.md
    └── workflows/
        └── security.yml    # Security review on PRs
```

## Community Links

- [azmsh.net](https://azmsh.net) -- Arizona Meshtastic community home
- [map.azmsh.net](https://map.azmsh.net) -- Live mesh map
- [view.azmsh.net](https://view.azmsh.net) -- Mesh viewer
- [metrics.azmsh.net](https://metrics.azmsh.net) -- Network metrics (Grafana)
- [flasher.meshtastic.org](https://flasher.meshtastic.org) -- Firmware flasher

## Contributing

1. Fork the repo
2. Create a feature branch
3. Make your changes (all client-side JS, no build step needed)
4. Test by opening `index.html` locally
5. Submit a PR

Config recommendations come from the Arizona Meshtastic community. If the recommendations change, update the constants in `js/checker.js`.

## License

MIT
