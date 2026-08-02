/**
 * fixer.js — Config auto-fix and export for Arizona Meshtastic Config Checker
 *
 * Takes a parsed config and the selected region/nodeType, applies all AZ
 * community recommended values to failing settings, and exports in the
 * same format the config was originally uploaded in:
 *   - Android .cfg binary → .cfg binary (protobuf DeviceProfile)
 *   - iOS/Web JSON → JSON export
 *   - CLI YAML → YAML export
 *
 * All processing happens in the browser. Nothing leaves the device.
 */

import { ConfigParser } from './parser.js';
import { encodeChannelUrl } from './channel-url.js';

import {
  METRO_RECOMMENDATIONS as METRO,
  RURAL_RECOMMENDATIONS as RURAL,
  BROADCAST_MOBILE as MOBILE,
  BROADCAST_STATIONARY as STATIONARY,
  NEIGHBORINFO_RECOMMENDATIONS as NEIGHBORINFO
} from './constants.js';

  /**
   * Get the combined recommendation set for a given region + nodeType.
   */
  function getRecommendations(region, nodeType) {
    const lora = region === 'metro' ? METRO : RURAL;
    const broadcast = nodeType === 'mobile' ? MOBILE : STATIONARY;
    return { ...lora, ...broadcast, neighborInfo: NEIGHBORINFO };
  }

  /**
   * Deep-clone a config object and apply recommended values to any
   * setting that failed or warned during the check.
   *
   * Accepts optional overrides from user-editable fields and MQTT form.
   *
   * Returns a new config object (does not mutate the original).
   */
  function fix(config, region, nodeType, userOverrides, mqttConfig) {
    // Deep clone
    const fixed = JSON.parse(JSON.stringify(config));
    const rec = getRecommendations(region, nodeType);

    // LoRa
    fixed.config.lora.modemPreset = rec.modemPreset;
    fixed.config.lora.channelNum = rec.channelNum;
    fixed.config.lora.usePreset = true;
    fixed.config.lora.configOkToMqtt = true;
    fixed.config.lora.overrideFrequency = 0;
    fixed.config.lora.hopLimit = 3;

    // Device
    fixed.config.device.nodeInfoBroadcastSecs = rec.nodeInfoBroadcastSecs;

    // Position
    fixed.config.position.positionBroadcastSecs = rec.positionBroadcastSecs;
    fixed.config.position.gpsUpdateInterval = rec.gpsUpdateInterval;

    if (nodeType === 'mobile') {
      fixed.config.position.positionBroadcastSmartEnabled = true;
      fixed.config.position.broadcastSmartMinimumDistance = rec.smartMinDistance;
      fixed.config.position.broadcastSmartMinimumIntervalSecs = rec.smartMinInterval;
    } else {
      fixed.config.position.positionBroadcastSmartEnabled = false;
    }

    // Telemetry
    fixed.moduleConfig.telemetry.deviceUpdateInterval = rec.deviceMetricsInterval;

    // NeighborInfo (stationary nodes)
    if (nodeType === 'stationary') {
      if (!fixed.moduleConfig.neighborInfo) {
        fixed.moduleConfig.neighborInfo = {};
      }
      fixed.moduleConfig.neighborInfo.enabled = NEIGHBORINFO.enabled;
      fixed.moduleConfig.neighborInfo.transmitOverLora = NEIGHBORINFO.transmitOverLora;
      fixed.moduleConfig.neighborInfo.updateInterval = NEIGHBORINFO.updateInterval;
    }

    // MQTT — apply from MQTT config form if provided
    if (mqttConfig && mqttConfig.enabled) {
      fixed.moduleConfig.mqtt.enabled = true;
      if (mqttConfig.address) fixed.moduleConfig.mqtt.address = mqttConfig.address;
      if (mqttConfig.username) fixed.moduleConfig.mqtt.username = mqttConfig.username;
      if (mqttConfig.password) fixed.moduleConfig.mqtt.password = mqttConfig.password;
      if (mqttConfig.root) fixed.moduleConfig.mqtt.root = mqttConfig.root;
      if (mqttConfig.proxyToClientEnabled != null) {
        fixed.moduleConfig.mqtt.proxyToClientEnabled = mqttConfig.proxyToClientEnabled;
      }
      fixed.moduleConfig.mqtt.mapReportingEnabled = mqttConfig.mapReportingEnabled || false;
      if (mqttConfig.mapReportInterval && mqttConfig.mapReportingEnabled) {
        if (!fixed.moduleConfig.mqtt.mapReportSettings) {
          fixed.moduleConfig.mqtt.mapReportSettings = {};
        }
        fixed.moduleConfig.mqtt.mapReportSettings.publishIntervalSecs = mqttConfig.mapReportInterval;
      }
    }

    // Apply user overrides from editable fields
    if (userOverrides && typeof userOverrides === 'object') {
      for (const [key, value] of Object.entries(userOverrides)) {
        applyOverride(fixed, key, value);
      }
    }

    return fixed;
  }

  /**
   * Parse a human-readable time string into seconds (mirrors app.js parseTimeInput).
   * Supports: plain numbers (seconds), Nm/Nmin, Nh/Nhr, Nd.
   */
  function parseTimeSecs(str) {
    if (str == null) return NaN;
    const s = String(str).trim().toLowerCase();
    if (s === '') return NaN;
    const match = s.match(/^([0-9]*\.?[0-9]+)\s*(d|days?|h|hr|hrs|hours?|m|min|mins|minutes?|s|sec|secs|seconds?)?$/);
    if (!match) {
      const n = Number(s);
      return isNaN(n) ? NaN : n;
    }
    const num = parseFloat(match[1]);
    const unit = match[2] || '';
    if (!unit || unit.startsWith('s')) return Math.round(num);
    if (unit.startsWith('m')) return Math.round(num * 60);
    if (unit.startsWith('h')) return Math.round(num * 3600);
    if (unit.startsWith('d')) return Math.round(num * 86400);
    return Math.round(num);
  }

  /**
   * Parse an integer from a value that may contain human-readable time format.
   * Falls back to parseInt for non-time values.
   */
  function parseTimeOrInt(value) {
    const t = parseTimeSecs(value);
    if (!isNaN(t)) return t;
    return parseInt(value) || 0;
  }

  /**
   * Apply a single user override to the config object by setting key path.
   */
  function applyOverride(config, key, value) {
    const parts = key.split('.');
    if (parts.length < 2) return;

    const section = parts[0];
    const field = parts.slice(1).join('.');

    switch (section) {
      case 'lora':
        if (field === 'modemPreset') {
          // Resolve string preset name to number
          const num = resolvePreset(value);
          if (num != null) config.config.lora.modemPreset = num;
        } else if (field === 'channelNum') {
          config.config.lora.channelNum = parseInt(value) || 0;
        } else if (field === 'usePreset') {
          config.config.lora.usePreset = parseBool(value);
        } else if (field === 'configOkToMqtt') {
          config.config.lora.configOkToMqtt = parseBool(value);
        } else if (field === 'hopLimit') {
          config.config.lora.hopLimit = parseInt(value) || 3;
        } else if (field === 'overrideFrequency') {
          config.config.lora.overrideFrequency = parseFloat(value) || 0;
        }
        break;
      case 'device':
        if (field === 'nodeInfoBroadcastSecs') {
          config.config.device.nodeInfoBroadcastSecs = parseTimeOrInt(value);
        } else if (field === 'role') {
          const roleNum = resolveRole(value);
          if (roleNum != null) config.config.device.role = roleNum;
        }
        break;
      case 'position':
        if (field === 'positionBroadcastSecs') {
          config.config.position.positionBroadcastSecs = parseTimeOrInt(value);
        } else if (field === 'gpsUpdateInterval') {
          config.config.position.gpsUpdateInterval = parseTimeOrInt(value);
        } else if (field === 'positionBroadcastSmartEnabled') {
          config.config.position.positionBroadcastSmartEnabled = parseBool(value);
        } else if (field === 'broadcastSmartMinimumDistance') {
          config.config.position.broadcastSmartMinimumDistance = parseInt(value) || 0;
        } else if (field === 'broadcastSmartMinimumIntervalSecs') {
          config.config.position.broadcastSmartMinimumIntervalSecs = parseTimeOrInt(value);
        }
        break;
      case 'telemetry':
        if (field === 'deviceUpdateInterval') {
          config.moduleConfig.telemetry.deviceUpdateInterval = parseTimeOrInt(value);
        }
        break;
      case 'mqtt':
        if (field === 'address') config.moduleConfig.mqtt.address = String(value);
        else if (field === 'username') config.moduleConfig.mqtt.username = String(value);
        else if (field === 'password') config.moduleConfig.mqtt.password = String(value);
        else if (field === 'root') config.moduleConfig.mqtt.root = String(value);
        else if (field === 'mapReportInterval') {
          if (!config.moduleConfig.mqtt.mapReportSettings) {
            config.moduleConfig.mqtt.mapReportSettings = {};
          }
          config.moduleConfig.mqtt.mapReportSettings.publishIntervalSecs = parseTimeOrInt(value);
        }
        break;
      case 'neighborInfo':
        if (!config.moduleConfig.neighborInfo) config.moduleConfig.neighborInfo = {};
        if (field === 'enabled') config.moduleConfig.neighborInfo.enabled = parseBool(value);
        else if (field === 'transmitOverLora') config.moduleConfig.neighborInfo.transmitOverLora = parseBool(value);
        else if (field === 'updateInterval') config.moduleConfig.neighborInfo.updateInterval = parseTimeOrInt(value);
        break;
    }
  }

  function parseBool(v) {
    if (typeof v === 'boolean') return v;
    if (typeof v === 'string') {
      const lower = v.toLowerCase().trim();
      return lower === 'true' || lower === 'enabled' || lower === 'on' || lower === 'yes' || lower === '1';
    }
    return !!v;
  }

  function resolvePreset(v) {
    if (typeof v === 'number') return v;
    const str = String(v).toUpperCase().replace(/ /g, '_').replace(/-/g, '_');
    for (const [num, name] of Object.entries(ConfigParser.MODEM_PRESET_NAMES)) {
      if (name === str) return Number(num);
    }
    const n = parseInt(v);
    return isNaN(n) ? null : n;
  }

  function resolveRole(v) {
    if (typeof v === 'number') return v;
    const str = String(v).toUpperCase().replace(/ /g, '_').replace(/-/g, '_');
    for (const [num, name] of Object.entries(ConfigParser.ROLE_NAMES)) {
      if (name === str) return Number(num);
    }
    const n = parseInt(v);
    return isNaN(n) ? null : n;
  }

  /**
   * Build a new config from scratch with default AZ community settings.
   */
  function buildNewConfig(options) {
    const { longName, shortName, region, nodeType, role, hopLimit } = options;
    const lora = region === 'metro' ? METRO : RURAL;
    const broadcast = nodeType === 'mobile' ? MOBILE : STATIONARY;

    const config = {
      source: 'yaml',
      longName: longName || '',
      shortName: shortName || '',
      channelUrl: '',
      firmwareVersion: 0,
      config: {
        device: {
          role: parseInt(role) || 0,
          nodeInfoBroadcastSecs: broadcast.nodeInfoBroadcastSecs,
          rebroadcastMode: 0
        },
        position: {
          positionBroadcastSecs: broadcast.positionBroadcastSecs,
          positionBroadcastSmartEnabled: broadcast.smartBroadcast || false,
          fixedPosition: nodeType === 'stationary',
          gpsUpdateInterval: broadcast.gpsUpdateInterval,
          gpsMode: 0,
          broadcastSmartMinimumDistance: broadcast.smartMinDistance || 0,
          broadcastSmartMinimumIntervalSecs: broadcast.smartMinInterval || 0
        },
        lora: {
          usePreset: true,
          modemPreset: lora.modemPreset,
          channelNum: lora.channelNum,
          region: 1,  // US
          hopLimit: parseInt(hopLimit) || 3,
          txEnabled: true,
          txPower: 0,
          overrideFrequency: 0,
          configOkToMqtt: true,
          ignoreMqtt: false
        },
        power: {},
        network: {},
        display: {},
        bluetooth: {},
        security: {}
      },
      moduleConfig: {
        mqtt: {
          enabled: false,
          address: '',
          username: '',
          password: '',
          encryptionEnabled: false,
          jsonEnabled: false,
          tlsEnabled: false,
          root: '',
          proxyToClientEnabled: false,
          mapReportingEnabled: false,
          mapReportSettings: {}
        },
        telemetry: {
          deviceUpdateInterval: broadcast.deviceMetricsInterval,
          environmentUpdateInterval: 0
        },
        neighborInfo: {
          enabled: nodeType === 'stationary',
          transmitOverLora: nodeType === 'stationary',
          updateInterval: nodeType === 'stationary' ? NEIGHBORINFO.updateInterval : 0
        }
      },
      channels: [
        {
          index: 0,
          name: '',
          psk: 'AQ==',
          uplinkEnabled: true,
          downlinkEnabled: false,
          role: 1
        }
      ]
    };

    return config;
  }

  /**
   * Convert a normalized config object to a YAML string that is compatible
   * with `meshtastic --import-config`.
   *
   * Uses snake_case field names to match the Meshtastic CLI format.
   */
  function toYAML(config) {
    const presetNames = ConfigParser.MODEM_PRESET_NAMES;
    const roleNames = ConfigParser.ROLE_NAMES;

    const lines = [];
    lines.push('# Arizona Meshtastic Community - Config');
    lines.push('# Generated by config.azmsh.net');
    lines.push('# Import with: meshtastic --import-config meshtastic-config-fixed.yaml');
    lines.push('');

    // Owner
    if (config.longName || config.shortName) {
      lines.push('owner:');
      if (config.longName) lines.push(`  long_name: "${config.longName}"`);
      if (config.shortName) lines.push(`  short_name: "${config.shortName}"`);
      lines.push('');
    }

    // Device
    lines.push('device:');
    lines.push(`  role: ${roleNames[config.config.device.role] || 'CLIENT'}`);
    lines.push(`  node_info_broadcast_secs: ${config.config.device.nodeInfoBroadcastSecs}`);
    lines.push('');

    // LoRa
    lines.push('lora:');
    lines.push(`  use_preset: true`);
    lines.push(`  modem_preset: ${presetNames[config.config.lora.modemPreset] || 'LONG_FAST'}`);
    lines.push(`  channel_num: ${config.config.lora.channelNum}`);
    lines.push(`  region: US`);
    if (config.config.lora.hopLimit) {
      lines.push(`  hop_limit: ${config.config.lora.hopLimit}`);
    }
    lines.push(`  tx_enabled: true`);
    lines.push(`  config_ok_to_mqtt: true`);
    lines.push('');

    // Position
    lines.push('position:');
    lines.push(`  position_broadcast_secs: ${config.config.position.positionBroadcastSecs}`);
    lines.push(`  position_broadcast_smart_enabled: ${config.config.position.positionBroadcastSmartEnabled}`);
    if (config.config.position.fixedPosition) {
      lines.push(`  fixed_position: true`);
    }
    lines.push(`  gps_update_interval: ${config.config.position.gpsUpdateInterval}`);
    if (config.config.position.positionBroadcastSmartEnabled) {
      lines.push(`  broadcast_smart_minimum_distance: ${config.config.position.broadcastSmartMinimumDistance}`);
      lines.push(`  broadcast_smart_minimum_interval_secs: ${config.config.position.broadcastSmartMinimumIntervalSecs}`);
    }
    lines.push('');

    // Module config
    lines.push('module:');

    // MQTT
    lines.push('  mqtt:');
    lines.push(`    enabled: ${config.moduleConfig.mqtt.enabled}`);
    if (config.moduleConfig.mqtt.enabled) {
      if (config.moduleConfig.mqtt.address) {
        lines.push(`    address: "${config.moduleConfig.mqtt.address}"`);
      }
      if (config.moduleConfig.mqtt.username) {
        lines.push(`    username: "${config.moduleConfig.mqtt.username}"`);
      }
      if (config.moduleConfig.mqtt.password) {
        lines.push(`    password: "${config.moduleConfig.mqtt.password}"`);
      }
      if (config.moduleConfig.mqtt.root) {
        lines.push(`    root: "${config.moduleConfig.mqtt.root}"`);
      }
      lines.push(`    encryption_enabled: ${config.moduleConfig.mqtt.encryptionEnabled}`);
      lines.push(`    map_reporting_enabled: ${config.moduleConfig.mqtt.mapReportingEnabled}`);
      if (config.moduleConfig.mqtt.proxyToClientEnabled) {
        lines.push(`    proxy_to_client_enabled: true`);
      }
      if (config.moduleConfig.mqtt.mapReportingEnabled && config.moduleConfig.mqtt.mapReportSettings) {
        const interval = config.moduleConfig.mqtt.mapReportSettings.publishIntervalSecs;
        if (interval) {
          lines.push('    map_report_settings:');
          lines.push(`      publish_interval_secs: ${interval}`);
        }
      }
    }

    // Telemetry
    lines.push('  telemetry:');
    lines.push(`    device_update_interval: ${config.moduleConfig.telemetry.deviceUpdateInterval}`);
    if (config.moduleConfig.telemetry.environmentUpdateInterval) {
      lines.push(`    environment_update_interval: ${config.moduleConfig.telemetry.environmentUpdateInterval}`);
    }

    // NeighborInfo
    if (config.moduleConfig.neighborInfo && config.moduleConfig.neighborInfo.enabled) {
      lines.push('  neighbor_info:');
      lines.push(`    enabled: true`);
      lines.push(`    transmit_over_lora: ${config.moduleConfig.neighborInfo.transmitOverLora}`);
      lines.push(`    update_interval: ${config.moduleConfig.neighborInfo.updateInterval}`);
    }

    lines.push('');
    return lines.join('\n');
  }

  /**
   * Convert a normalized config object to a JSON string matching the
   * iOS/Web JSON export structure.
   */
  function toJSON(config) {
    const presetNames = ConfigParser.MODEM_PRESET_NAMES;
    const roleNames = ConfigParser.ROLE_NAMES;
    const regionNames = ConfigParser.REGION_NAMES;

    const doc = {
      owner: {
        longName: config.longName || '',
        shortName: config.shortName || ''
      },
      config: {
        device: {
          role: roleNames[config.config.device.role] || 'CLIENT',
          nodeInfoBroadcastSecs: config.config.device.nodeInfoBroadcastSecs
        },
        position: {
          positionBroadcastSecs: config.config.position.positionBroadcastSecs,
          positionBroadcastSmartEnabled: config.config.position.positionBroadcastSmartEnabled,
          fixedPosition: config.config.position.fixedPosition || false,
          gpsUpdateInterval: config.config.position.gpsUpdateInterval,
          broadcastSmartMinimumDistance: config.config.position.broadcastSmartMinimumDistance || 0,
          broadcastSmartMinimumIntervalSecs: config.config.position.broadcastSmartMinimumIntervalSecs || 0
        },
        lora: {
          usePreset: true,
          modemPreset: presetNames[config.config.lora.modemPreset] || 'LONG_FAST',
          channelNum: config.config.lora.channelNum,
          region: regionNames[config.config.lora.region] || 'US',
          hopLimit: config.config.lora.hopLimit || 0,
          txEnabled: true,
          configOkToMqtt: true
        }
      },
      moduleConfig: {
        mqtt: {
          enabled: config.moduleConfig.mqtt.enabled,
          address: config.moduleConfig.mqtt.address,
          username: config.moduleConfig.mqtt.username,
          password: config.moduleConfig.mqtt.password,
          root: config.moduleConfig.mqtt.root || '',
          encryptionEnabled: config.moduleConfig.mqtt.encryptionEnabled,
          proxyToClientEnabled: config.moduleConfig.mqtt.proxyToClientEnabled || false,
          mapReportingEnabled: config.moduleConfig.mqtt.mapReportingEnabled,
          mapReportSettings: config.moduleConfig.mqtt.mapReportSettings || {}
        },
        telemetry: {
          deviceUpdateInterval: config.moduleConfig.telemetry.deviceUpdateInterval,
          environmentUpdateInterval: config.moduleConfig.telemetry.environmentUpdateInterval || 0
        },
        neighborInfo: config.moduleConfig.neighborInfo || {
          enabled: false,
          transmitOverLora: false,
          updateInterval: 0
        }
      }
    };

    if (config.channelUrl) {
      doc.channelUrl = config.channelUrl;
    }

    return JSON.stringify(doc, null, 2);
  }

  /**
   * Convert a normalized config object to a binary protobuf (DeviceProfile)
   * matching the Android .cfg export format.
   *
   * Returns a Uint8Array of the encoded protobuf.
   */
  function toBinary(config) {
    const root = protobuf.Root.fromJSON(window.MeshtasticProto);
    const DeviceProfile = root.lookupType('meshtastic.DeviceProfile');

    // Build the DeviceProfile message from our normalized config
    // Encode channels into channelUrl (issue #20). DeviceProfile has no
    // `channels` field, so channels MUST ride in the shareable channel URL or
    // they are silently dropped on export. If we have channels, (re)build the
    // URL from them; otherwise preserve any existing channelUrl.
    let channelUrl = config.channelUrl || '';
    if (config.channels && config.channels.length > 0) {
      try {
        channelUrl = encodeChannelUrl(config.channels, {
          usePreset: true,
          modemPreset: config.config.lora.modemPreset,
          channelNum: config.config.lora.channelNum,
          region: config.config.lora.region
        });
      } catch (e) {
        // Fall back to whatever URL we already had rather than failing export.
        channelUrl = config.channelUrl || '';
      }
    }

    const profile = {
      longName: config.longName || '',
      shortName: config.shortName || '',
      channelUrl: channelUrl,
      config: {
        device: {
          role: config.config.device.role,
          nodeInfoBroadcastSecs: config.config.device.nodeInfoBroadcastSecs
        },
        position: {
          positionBroadcastSecs: config.config.position.positionBroadcastSecs,
          positionBroadcastSmartEnabled: config.config.position.positionBroadcastSmartEnabled,
          fixedPosition: config.config.position.fixedPosition || false,
          gpsUpdateInterval: config.config.position.gpsUpdateInterval,
          broadcastSmartMinimumDistance: config.config.position.broadcastSmartMinimumDistance || 0,
          broadcastSmartMinimumIntervalSecs: config.config.position.broadcastSmartMinimumIntervalSecs || 0,
          gpsMode: config.config.position.gpsMode || 0
        },
        lora: {
          usePreset: true,
          modemPreset: config.config.lora.modemPreset,
          channelNum: config.config.lora.channelNum,
          region: config.config.lora.region,
          hopLimit: config.config.lora.hopLimit || 0,
          txEnabled: true,
          txPower: config.config.lora.txPower || 0,
          overrideFrequency: 0,
          configOkToMqtt: true,
          ignoreMqtt: config.config.lora.ignoreMqtt || false
        },
        bluetooth: config.config.bluetooth || {},
        security: config.config.security || {}
      },
      moduleConfig: {
        mqtt: {
          enabled: config.moduleConfig.mqtt.enabled,
          address: config.moduleConfig.mqtt.address || '',
          username: config.moduleConfig.mqtt.username || '',
          password: config.moduleConfig.mqtt.password || '',
          encryptionEnabled: config.moduleConfig.mqtt.encryptionEnabled || false,
          jsonEnabled: config.moduleConfig.mqtt.jsonEnabled || false,
          tlsEnabled: config.moduleConfig.mqtt.tlsEnabled || false,
          root: config.moduleConfig.mqtt.root || '',
          proxyToClientEnabled: config.moduleConfig.mqtt.proxyToClientEnabled || false,
          mapReportingEnabled: config.moduleConfig.mqtt.mapReportingEnabled || false
        },
        telemetry: {
          deviceUpdateInterval: config.moduleConfig.telemetry.deviceUpdateInterval,
          environmentUpdateInterval: config.moduleConfig.telemetry.environmentUpdateInterval || 0
        }
      }
      // NOTE: DeviceProfile has no `channels` field — channels are carried in
      // `channelUrl` above (issue #20). Do not add a `channels` key here; it
      // would be silently dropped by the protobuf encoder.
    };

    const errMsg = DeviceProfile.verify(profile);
    if (errMsg) {
      throw new Error('Protobuf verification failed: ' + errMsg);
    }

    const message = DeviceProfile.create(profile);
    return DeviceProfile.encode(message).finish();
  }

  /**
   * Export a fixed config in the same format as the original upload.
   *
   * Returns { data, filename, mimeType } where data is either a string
   * (YAML/JSON) or Uint8Array (binary).
   */
  /**
   * Build an export filename from the original upload name.
   * Strips the extension, appends "-fixed", then adds the target extension.
   * Falls back to a generic name when no original filename is available.
   */
  function buildFilename(originalName, extension, isNew) {
    const suffix = isNew ? '' : '-fixed';
    if (!originalName) return `meshtastic-config${suffix}${extension}`;
    // Remove the last extension (e.g. ".cfg", ".yaml", ".json")
    const baseName = originalName.replace(/\.[^.]+$/, '');
    return `${baseName}${suffix}${extension}`;
  }

  function exportFixed(fixedConfig, originalFilename, isNew) {
    const source = fixedConfig.source;

    if ((source === 'android' || source === 'backup') && !isNew) {
      try {
        const bytes = toBinary(fixedConfig);
        return {
          data: bytes,
          filename: buildFilename(originalFilename, '.cfg', isNew),
          mimeType: 'application/octet-stream',
          formatLabel: '.cfg'
        };
      } catch (e) {
        // Fallback to YAML if binary encoding fails
        console.warn('Binary export failed, falling back to YAML:', e);
        return {
          data: toYAML(fixedConfig),
          filename: buildFilename(originalFilename, '.yaml', isNew),
          mimeType: 'text/yaml',
          formatLabel: '.yaml',
          fallbackNotice: 'Binary .cfg export failed \u2014 CLI YAML provided instead.'
        };
      }
    }

    if (source === 'json') {
      return {
        data: toJSON(fixedConfig),
        filename: buildFilename(originalFilename, '.json', isNew),
        mimeType: 'application/json',
        formatLabel: '.json'
      };
    }

    // Default: YAML (for 'yaml' source or unknown or new configs)
    return {
      data: toYAML(fixedConfig),
      filename: buildFilename(originalFilename, '.yaml', isNew),
      mimeType: 'text/yaml',
      formatLabel: '.yaml'
    };
  }

  export const ConfigFixer = {
    fix,
    toYAML,
    toJSON,
    toBinary,
    exportFixed,
    getRecommendations,
    buildNewConfig
  };
