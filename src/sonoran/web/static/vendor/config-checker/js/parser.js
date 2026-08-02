/**
 * parser.js — Meshtastic config file parser
 *
 * Supports:
 *   - Android .cfg binary (protobuf DeviceProfile)
 *   - CLI YAML export
 *   - iOS/Web JSON export
 *
 * All parsing happens in the browser. Nothing leaves the device.
 *
 * Returns a normalized config object:
 * {
 *   source: 'android' | 'yaml' | 'json',
 *   longName: string,
 *   shortName: string,
 *   channelUrl: string,
 *   config: { device, position, power, network, display, lora, bluetooth, security },
 *   moduleConfig: { mqtt, telemetry, ... },
 *   channels: [ { name, psk, uplinkEnabled, downlinkEnabled, role } ]
 * }
 */
  import { decodeChannelUrl } from './channel-url.js';

  // Protobuf enum look-up tables
  const MODEM_PRESET_NAMES = {
    0: 'LONG_FAST', 1: 'LONG_SLOW', 2: 'VERY_LONG_SLOW',
    3: 'MEDIUM_SLOW', 4: 'MEDIUM_FAST', 5: 'SHORT_SLOW',
    6: 'SHORT_FAST', 7: 'LONG_MODERATE', 8: 'SHORT_TURBO', 9: 'LONG_TURBO'
  };

  const ROLE_NAMES = {
    0: 'CLIENT', 1: 'CLIENT_MUTE', 2: 'ROUTER', 3: 'ROUTER_CLIENT',
    4: 'REPEATER', 5: 'TRACKER', 6: 'SENSOR', 7: 'TAK',
    8: 'CLIENT_HIDDEN', 9: 'LOST_AND_FOUND', 10: 'TAK_TRACKER',
    11: 'ROUTER_LATE', 12: 'CLIENT_BASE'
  };

  const REGION_NAMES = {
    0: 'UNSET', 1: 'US', 2: 'EU_433', 3: 'EU_868', 4: 'CN', 5: 'JP',
    6: 'ANZ', 7: 'KR', 8: 'TW', 9: 'RU', 10: 'IN', 11: 'NZ_865', 12: 'TH'
  };

  /**
   * Try to detect the file format from raw bytes / text.
   */
  function detectFormat(buffer, fileName) {
    const ext = (fileName || '').toLowerCase().split('.').pop();

    // If it's a YAML or JSON extension, try text parse
    if (['yaml', 'yml'].includes(ext)) return 'yaml';
    if (ext === 'json') return 'json';
    if (ext === 'cfg') return 'binary';

    // Heuristic: try to decode as UTF-8 and see if it looks like YAML/JSON
    try {
      const text = new TextDecoder('utf-8', { fatal: true }).decode(buffer.slice(0, 512));
      const trimmed = text.trim();
      if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json';
      if (trimmed.includes(':') && !trimmed.includes('\0')) return 'yaml';
    } catch (e) {
      // Not valid UTF-8 text — likely binary
    }
    return 'binary';
  }

  /**
   * Parse binary protobuf (Android .cfg export).
   * The Android app exports a DeviceProfile protobuf.
   */
  async function parseBinary(buffer) {
    const root = protobuf.Root.fromJSON(window.MeshtasticProto);
    const DeviceProfile = root.lookupType('meshtastic.DeviceProfile');

    let decoded;
    let source = 'android';
    let channels = [];

    try {
      decoded = DeviceProfile.decode(new Uint8Array(buffer));
    } catch (e) {
      throw new Error(
        'Unable to decode binary file. Make sure this is a Meshtastic config export (.cfg).\n' +
        'DeviceProfile error: ' + e.message
      );
    }

    // DeviceProfile (the Android .cfg format) has NO `channels` field — channels
    // are carried in `channelUrl` (issue #20). BackupPreferences-style exports
    // may carry a real `channels` array; honor that first if present.
    if (decoded.channels && Array.isArray(decoded.channels) && decoded.channels.length > 0) {
      channels = decoded.channels;
      return normalize(decoded, channels, source);
    }

    // No embedded channel list — decode the shareable channel URL instead.
    // decodeChannelUrl returns already-normalized channel objects, so we let
    // normalize() leave them as-is (it maps ch.settings only when present).
    if (decoded.channelUrl) {
      const urlChannels = decodeChannelUrl(decoded.channelUrl);
      if (urlChannels.length > 0) {
        const result = normalize(decoded, [], source);
        result.channels = urlChannels;
        return result;
      }
    }

    return normalize(decoded, channels, source);
  }

  /**
   * Parse YAML (CLI export).
   */
  function parseYAML(text) {
    // js-yaml v4 removed SAFE_SCHEMA (load() is safe by default and never
    // constructs functions). Fall back gracefully across versions.
    const schema = jsyaml.SAFE_SCHEMA || jsyaml.DEFAULT_SCHEMA;
    const doc = jsyaml.load(text, { schema });
    return normalizeYamlJson(doc, 'yaml');
  }

  /**
   * Parse JSON (iOS / Web export).
   * Handles multiple JSON structures:
   *   - Direct config object (same shape as YAML)
   *   - iOS app export with nested myNodeInfo / radio / channels
   *   - Web client export with config wrapper
   */
  function parseJSON(text) {
    const doc = JSON.parse(text);

    // iOS app sometimes wraps config in a different structure
    // with myNodeInfo, radio, channels at the top level
    if (doc.myNodeInfo || doc.radio || doc.owner) {
      return normalizeIosJson(doc);
    }

    return normalizeYamlJson(doc, 'json');
  }

  /**
   * Normalize iOS-specific JSON export format.
   * iOS exports may have: { myNodeInfo, owner, radio, channels, config, moduleConfig }
   */
  function normalizeIosJson(doc) {
    const owner = doc.owner || {};
    const radio = doc.radio || {};
    const config = doc.config || radio.config || radio.preferences || {};

    // Build a normalized doc that normalizeYamlJson can handle
    const normalized = {
      long_name: owner.longName || owner.long_name || doc.longName || '',
      short_name: owner.shortName || owner.short_name || doc.shortName || '',
      firmware_version: doc.firmwareVersion || doc.firmware_version ||
                        (doc.myNodeInfo ? doc.myNodeInfo.firmware_version || doc.myNodeInfo.firmwareVersion : '') || '',
      ...config
    };

    // Merge module config
    if (doc.moduleConfig) {
      normalized.module = doc.moduleConfig;
    } else if (radio.moduleConfig) {
      normalized.module = radio.moduleConfig;
    }

    // Merge channels
    if (doc.channels) {
      normalized.channels = doc.channels;
    }

    return normalizeYamlJson(normalized, 'json');
  }

  /**
   * Normalize YAML/JSON structure into our canonical format.
   * CLI exports typically look like:
   *   lora: { modem_preset: MEDIUM_FAST, ... }
   *   device: { role: CLIENT, ... }
   *   position: { ... }
   *   module:
   *     mqtt: { ... }
   *     telemetry: { ... }
   *   channels:
   *     - name: ...
   *       psk: ...
   */
  function normalizeYamlJson(doc, source) {
    if (!doc || typeof doc !== 'object') {
      throw new Error('Config file appears to be empty or invalid.');
    }

    // Handle nested "config" wrapper that some exports use
    const root = doc.config || doc;
    const mc = doc.module_config || doc.moduleConfig || doc.module || root.module_config || root.moduleConfig || root.module || {};

    // LoRa config
    const lora = root.lora || root.loRa || root.LoRa || {};
    const device = root.device || {};
    const position = root.position || {};
    const power = root.power || {};
    const network = root.network || {};
    const display = root.display || {};
    const bluetooth = root.bluetooth || {};
    const security = root.security || {};

    // Module config
    const mqtt = mc.mqtt || mc.MQTT || {};
    const telemetry = mc.telemetry || {};
    const neighborInfo = mc.neighbor_info || mc.neighborInfo || mc.neighbor || {};

    // Channels
    let channels = [];
    const chSrc = doc.channels || root.channels || [];
    if (Array.isArray(chSrc)) {
      channels = chSrc.map((ch, i) => ({
        index: ch.index != null ? ch.index : i,
        name: ch.name || (ch.settings ? ch.settings.name : '') || '',
        psk: ch.psk || (ch.settings ? ch.settings.psk : null) || ch.key || null,
        uplinkEnabled: ch.uplink_enabled || ch.uplinkEnabled || (ch.settings ? ch.settings.uplinkEnabled : false) || false,
        downlinkEnabled: ch.downlink_enabled || ch.downlinkEnabled || (ch.settings ? ch.settings.downlinkEnabled : false) || false,
        role: ch.role != null ? ch.role : (i === 0 ? 1 : (ch.name ? 2 : 0))
      }));
    }

    // Resolve enums from strings
    const resolvedModemPreset = resolveEnum(
      pick(lora, 'modem_preset', 'modemPreset', 'preset'),
      MODEM_PRESET_NAMES
    );
    const resolvedRole = resolveEnum(
      device.role,
      ROLE_NAMES
    );

    // Extract firmware version — may be in various locations
    const fwVersion = doc.firmware_version || doc.firmwareVersion || doc.fw_version ||
                      root.firmware_version || root.firmwareVersion || root.fw_version ||
                      doc.version || root.version || 0;

    return {
      source,
      longName: doc.long_name || doc.longName || root.long_name || root.longName || '',
      shortName: doc.short_name || doc.shortName || root.short_name || root.shortName || '',
      channelUrl: doc.channel_url || doc.channelUrl || '',
      firmwareVersion: fwVersion,
      config: {
        device: {
          role: resolvedRole,
          nodeInfoBroadcastSecs: numVal(pick(device, 'node_info_broadcast_secs', 'nodeInfoBroadcastSecs')),
          rebroadcastMode: numVal(pick(device, 'rebroadcast_mode', 'rebroadcastMode'))
        },
        position: {
          positionBroadcastSecs: numVal(pick(position, 'position_broadcast_secs', 'positionBroadcastSecs')),
          positionBroadcastSmartEnabled: boolVal(pick(position, 'position_broadcast_smart_enabled', 'positionBroadcastSmartEnabled')),
          fixedPosition: boolVal(pick(position, 'fixed_position', 'fixedPosition')),
          gpsUpdateInterval: numVal(pick(position, 'gps_update_interval', 'gpsUpdateInterval')),
          gpsMode: numVal(pick(position, 'gps_mode', 'gpsMode')),
          broadcastSmartMinimumDistance: numVal(pick(position, 'broadcast_smart_minimum_distance', 'broadcastSmartMinimumDistance')),
          broadcastSmartMinimumIntervalSecs: numVal(pick(position, 'broadcast_smart_minimum_interval_secs', 'broadcastSmartMinimumIntervalSecs'))
        },
        lora: {
          usePreset: boolVal(lora.use_preset != null ? lora.use_preset : (lora.usePreset != null ? lora.usePreset : true)),
          modemPreset: resolvedModemPreset,
          channelNum: numVal(pick(lora, 'channel_num', 'channelNum')),
          region: resolveEnum(lora.region, REGION_NAMES),
          hopLimit: numVal(pick(lora, 'hop_limit', 'hopLimit')),
          txEnabled: boolVal(pick(lora, 'tx_enabled', 'txEnabled')),
          txPower: numVal(pick(lora, 'tx_power', 'txPower')),
          overrideFrequency: numVal(pick(lora, 'override_frequency', 'overrideFrequency')),
          configOkToMqtt: boolVal(pick(lora, 'config_ok_to_mqtt', 'configOkToMqtt', 'ok_to_mqtt', 'okToMqtt')),
          ignoreMqtt: boolVal(pick(lora, 'ignore_mqtt', 'ignoreMqtt'))
        },
        power: {},
        network: {},
        display: {},
        bluetooth: {},
        security: {}
      },
      moduleConfig: {
        mqtt: {
          enabled: boolVal(mqtt.enabled),
          address: mqtt.address || mqtt.server || '',
          username: mqtt.username || '',
          password: mqtt.password || '',
          encryptionEnabled: boolVal(pick(mqtt, 'encryption_enabled', 'encryptionEnabled')),
          jsonEnabled: boolVal(pick(mqtt, 'json_enabled', 'jsonEnabled')),
          tlsEnabled: boolVal(pick(mqtt, 'tls_enabled', 'tlsEnabled')),
          root: mqtt.root || mqtt.topic || '',
          proxyToClientEnabled: boolVal(pick(mqtt, 'proxy_to_client_enabled', 'proxyToClientEnabled')),
          mapReportingEnabled: boolVal(pick(mqtt, 'map_reporting_enabled', 'mapReportingEnabled')),
          mapReportSettings: mqtt.map_report_settings || mqtt.mapReportSettings || {}
        },
        telemetry: {
          deviceUpdateInterval: numVal(pick(telemetry, 'device_update_interval', 'deviceUpdateInterval', 'device_metrics_update_interval', 'deviceMetricsUpdateInterval')),
          environmentUpdateInterval: numVal(pick(telemetry, 'environment_update_interval', 'environmentUpdateInterval', 'environment_metrics_update_interval', 'environmentMetricsUpdateInterval'))
        },
        neighborInfo: {
          enabled: boolVal(pick(neighborInfo, 'enabled')),
          transmitOverLora: boolVal(pick(neighborInfo, 'transmit_over_lora', 'transmitOverLora')),
          updateInterval: numVal(pick(neighborInfo, 'update_interval', 'updateInterval'))
        }
      },
      channels
    };
  }

  /**
   * Normalize a decoded protobuf DeviceProfile into our canonical format.
   */
  function normalize(decoded, channels, source) {
    const config = decoded.config || {};
    const mc = decoded.moduleConfig || {};
    const lora = config.lora || {};
    const device = config.device || {};
    const position = config.position || {};
    const mqtt = mc.mqtt || {};
    const neighborInfoBin = mc.neighborInfo || {};

    // Extract firmware version from config version field if present
    const configVersion = config.version || 0;

    return {
      source,
      longName: decoded.longName || '',
      shortName: decoded.shortName || '',
      channelUrl: decoded.channelUrl || '',
      firmwareVersion: configVersion,
      config: {
        device: {
          role: numVal(device.role),
          nodeInfoBroadcastSecs: numVal(device.nodeInfoBroadcastSecs),
          rebroadcastMode: numVal(device.rebroadcastMode)
        },
        position: {
          positionBroadcastSecs: numVal(position.positionBroadcastSecs),
          positionBroadcastSmartEnabled: boolVal(position.positionBroadcastSmartEnabled),
          fixedPosition: boolVal(position.fixedPosition),
          gpsUpdateInterval: numVal(position.gpsUpdateInterval),
          gpsMode: numVal(position.gpsMode),
          broadcastSmartMinimumDistance: numVal(position.broadcastSmartMinimumDistance),
          broadcastSmartMinimumIntervalSecs: numVal(position.broadcastSmartMinimumIntervalSecs)
        },
        lora: {
          usePreset: lora.usePreset != null ? boolVal(lora.usePreset) : true,
          modemPreset: numVal(lora.modemPreset),
          channelNum: numVal(lora.channelNum),
          region: numVal(lora.region),
          hopLimit: numVal(lora.hopLimit),
          txEnabled: lora.txEnabled != null ? boolVal(lora.txEnabled) : true,
          txPower: numVal(lora.txPower),
          overrideFrequency: numVal(lora.overrideFrequency),
          configOkToMqtt: boolVal(lora.configOkToMqtt),
          ignoreMqtt: boolVal(lora.ignoreMqtt)
        },
        power: config.power || {},
        network: config.network || {},
        display: config.display || {},
        bluetooth: config.bluetooth || {},
        security: config.security || {}
      },
      moduleConfig: {
        mqtt: {
          enabled: boolVal(mqtt.enabled),
          address: mqtt.address || '',
          username: mqtt.username || '',
          password: mqtt.password || '',
          encryptionEnabled: boolVal(mqtt.encryptionEnabled),
          jsonEnabled: boolVal(mqtt.jsonEnabled),
          tlsEnabled: boolVal(mqtt.tlsEnabled),
          root: mqtt.root || '',
          proxyToClientEnabled: boolVal(mqtt.proxyToClientEnabled),
          mapReportingEnabled: boolVal(mqtt.mapReportingEnabled),
          mapReportSettings: mqtt.mapReportSettings || {}
        },
        telemetry: {
          deviceUpdateInterval: numVal(mc.telemetry ? mc.telemetry.deviceUpdateInterval : 0),
          environmentUpdateInterval: numVal(mc.telemetry ? mc.telemetry.environmentUpdateInterval : 0)
        },
        neighborInfo: {
          enabled: boolVal(neighborInfoBin.enabled),
          transmitOverLora: boolVal(neighborInfoBin.transmitOverLora),
          updateInterval: numVal(neighborInfoBin.updateInterval)
        }
      },
      channels: (channels || []).map((ch, i) => ({
        index: ch.index != null ? ch.index : i,
        name: ch.settings ? ch.settings.name : '',
        psk: ch.settings ? ch.settings.psk : null,
        uplinkEnabled: ch.settings ? ch.settings.uplinkEnabled : false,
        downlinkEnabled: ch.settings ? ch.settings.downlinkEnabled : false,
        role: ch.role != null ? ch.role : (i === 0 ? 1 : 0)
      }))
    };
  }

  // ---- Helpers ----

  /**
   * Pick the first non-null/non-undefined value from an object by key names.
   * Unlike `||`, this correctly handles falsy values like 0 and false.
   */
  function pick(obj, ...keys) {
    for (const k of keys) {
      if (obj[k] != null) return obj[k];
    }
    return undefined;
  }

  function numVal(v) {
    if (v == null) return 0;
    const n = Number(v);
    return isNaN(n) ? 0 : n;
  }

  function boolVal(v) {
    if (v == null) return false;
    if (typeof v === 'boolean') return v;
    if (typeof v === 'string') return v.toLowerCase() === 'true';
    return !!v;
  }

  /**
   * Resolve a value that might be a string enum name or a number.
   */
  function resolveEnum(val, nameMap) {
    if (val == null) return 0;
    if (typeof val === 'number') return val;
    if (typeof val === 'string') {
      const upper = val.toUpperCase().replace(/ /g, '_').replace(/-/g, '_');
      // Reverse look-up
      for (const [num, name] of Object.entries(nameMap)) {
        if (name === upper) return Number(num);
      }
      // Try parsing as a number string
      const n = Number(val);
      if (!isNaN(n)) return n;
    }
    return 0;
  }

  // ---- Public API ----

  export const ConfigParser = {
    MODEM_PRESET_NAMES,
    ROLE_NAMES,
    REGION_NAMES,

    /**
     * Main entry point. Returns a Promise that resolves to the normalized config.
     */
    async parse(buffer, fileName) {
      const format = detectFormat(buffer, fileName);

      if (format === 'binary') {
        return parseBinary(buffer);
      }

      const text = new TextDecoder('utf-8').decode(buffer);

      if (format === 'json') {
        return parseJSON(text);
      }

      return parseYAML(text);
    }
  };
