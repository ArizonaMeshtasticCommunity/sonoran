export const METRO_RECOMMENDATIONS = {
  modemPreset: 4,       // MEDIUM_FAST
  modemPresetName: 'MEDIUM_FAST',
  channelNum: 18,       // Frequency Slot 18
  okToMqtt: true,
};

export const RURAL_RECOMMENDATIONS = {
  modemPreset: 0,       // LONG_FAST
  modemPresetName: 'LONG_FAST',
  channelNum: 20,       // Frequency Slot 20
  okToMqtt: true,
};

/**
 * MQTT recommendations.
 *
 * The public AZ mesh MQTT credentials are not shipped in this source. The
 * checker cannot verify the username or password; it points users at the
 * community guide instead. The broker address is compared by hash.
 *
 * Threat model note: this is obfuscation against casual scraping/bots, not
 * cryptographic secrecy. The real credentials are distributed through the
 * Discord #getting-started guide / the azmsh.net site; the checker only
 * verifies, it never hands them out. The FIXER never injected these values —
 * users supply their own creds via the MQTT form — so hashing changes no
 * repair behavior.
 *
 * Hashes are sha256Hex(value) (see js/sha256.js). To rotate credentials,
 * recompute the hashes for the new values and replace below.
 */
export const MQTT_RECOMMENDATIONS = {
  // sha256(<AZ mesh broker host>)
  addressHash: '221fa1cd9c2cff798a71a6764728cfa5a00522870a0449022feaf9b61b21bd31',
  // Not shipped in the public source.
  usernameHash: null,
  // Not shipped in the public source.
  passwordHash: null,
  rootPrefix: 'msh/US/AZ/',
  uplinkEnabled: true,
  downlinkEnabled: false,
  // Display-only label for the broker (host is well-known; not a secret). Shown
  // in pass messages so users see what they matched. Kept generic to avoid
  // re-introducing a copy-pasteable cred block.
  addressLabel: 'the AZ mesh broker',
};

export const BROADCAST_MOBILE = {
  nodeInfoBroadcastSecs: 43200,
  smartBroadcast: true,
  smartMinDistance: 100,
  smartMinInterval: 60,
  positionBroadcastSecs: 3600,
  gpsUpdateInterval: 300,
  deviceMetricsInterval: 3600,
  mapReportInterval: 3600,
};

export const BROADCAST_STATIONARY = {
  nodeInfoBroadcastSecs: 43200,
  smartBroadcast: false,
  positionBroadcastSecs: 43200,
  gpsUpdateInterval: 21600,
  deviceMetricsInterval: 3600,
  mapReportInterval: 21600,
};

export const NEIGHBORINFO_RECOMMENDATIONS = {
  enabled: true,
  transmitOverLora: true,
  updateInterval: 39600,  // 11 hours
};

// Latest stable firmware — update this when new releases ship
export const LATEST_FIRMWARE = {
  version: '2.7.15',
  numericMin: 20715,  // Numeric version for comparison (major * 10000 + minor * 100 + patch)
  flasherUrl: 'https://flasher.meshtastic.org'
};

export const RECOMMENDED_ROLES = ['CLIENT', 'CLIENT_MUTE', 'CLIENT_BASE'];
export const ROLE_GUIDANCE = {
  CLIENT: 'Most nodes',
  CLIENT_MUTE: 'Pocket nodes or weak antenna',
  CLIENT_BASE: 'Rebroadcast traffic to/from favorited nodes'
};
