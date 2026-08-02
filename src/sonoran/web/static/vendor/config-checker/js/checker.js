/**
 * checker.js — Arizona Meshtastic Config Validation Engine
 *
 * Checks parsed config against AZ community recommendations and returns
 * a structured report with pass/fail/warn items grouped by category.
 *
 * Each check result:
 * {
 *   status: 'pass' | 'fail' | 'warn' | 'info',
 *   title: string,
 *   detail: string,
 *   current: string | null,
 *   expected: string | null,
 *   why: string | null,
 *   fix: string[] | null,   // step-by-step fix instructions
 *   settingKey: string | null  // key for editable settings
 * }
 */

import { ConfigParser } from './parser.js';
import { sha256Hex } from './sha256.js';

import {
  METRO_RECOMMENDATIONS,
  RURAL_RECOMMENDATIONS,
  MQTT_RECOMMENDATIONS,
  BROADCAST_MOBILE,
  BROADCAST_STATIONARY,
  NEIGHBORINFO_RECOMMENDATIONS,
  LATEST_FIRMWARE,
  RECOMMENDED_ROLES,
  ROLE_GUIDANCE
} from './constants.js';

  // ---- Utility ----

  function fmtSeconds(s) {
    if (!s || s === 0) return '0 (default)';
    if (s >= 86400) return `${s} (${(s / 86400).toFixed(1)}d)`;
    if (s >= 3600) return `${s} (${(s / 3600).toFixed(1)}h)`;
    if (s >= 60) return `${s} (${(s / 60).toFixed(0)}m)`;
    return `${s}s`;
  }

  function presetName(val) {
    return ConfigParser.MODEM_PRESET_NAMES[val] || `Unknown (${val})`;
  }

  function roleName(val) {
    return ConfigParser.ROLE_NAMES[val] || `Unknown (${val})`;
  }

  function pskDisplay(psk) {
    if (!psk) return 'None';
    if (psk instanceof Uint8Array || Array.isArray(psk)) {
      if (psk.length === 0) return 'None (empty)';
      if (psk.length === 1 && psk[0] === 0) return 'None (zero)';
      if (psk.length === 1 && psk[0] === 1) return 'Default key (AQ==)';
      if (psk.length === 1 && psk[0] >= 2 && psk[0] <= 10) return `Simple key ${psk[0] - 1}`;
      return `${psk.length * 8}-bit key (set)`;
    }
    if (typeof psk === 'string') {
      if (psk === '' || psk === 'AQ==' || psk === 'AQ') return 'Default key (AQ==)';
      return `Custom key (set)`;
    }
    return 'Unknown';
  }

  // ---- Check functions ----

  function checkLoRa(config, region) {
    const lora = config.config.lora;
    const rec = region === 'metro' ? METRO_RECOMMENDATIONS : RURAL_RECOMMENDATIONS;
    const checks = [];

    // Modem Preset
    const currentPreset = presetName(lora.modemPreset);
    const isPresetMatch = lora.modemPreset === rec.modemPreset;
    checks.push({
      status: isPresetMatch ? 'pass' : 'fail',
      title: 'Modem Preset',
      detail: isPresetMatch
        ? `Correctly set to ${rec.modemPresetName}`
        : `Should be ${rec.modemPresetName} for ${region === 'metro' ? 'metro' : 'rural'} areas`,
      current: currentPreset,
      expected: rec.modemPresetName,
      settingKey: 'lora.modemPreset',
      why: region === 'metro'
        ? 'Medium-Fast balances range and throughput for denser metro mesh networks.'
        : 'Long-Fast provides maximum range for sparse rural coverage.',
      fix: isPresetMatch ? null : [
        'Open Meshtastic app and connect to your node',
        'Go to Settings > LoRa',
        `Set Modem Preset to "${rec.modemPresetName.replace(/_/g, ' ')}"`,
        'Make sure "Use Preset" is enabled',
        'Save and reboot'
      ]
    });

    // Use Preset
    checks.push({
      status: lora.usePreset ? 'pass' : 'fail',
      title: 'Use Preset',
      detail: lora.usePreset ? 'Enabled (using standard preset)' : 'Disabled (custom LoRa parameters)',
      current: lora.usePreset ? 'Enabled' : 'Disabled',
      expected: 'Enabled',
      settingKey: 'lora.usePreset',
      why: 'Use Preset should be enabled so the modem preset controls your radio parameters. Disabling it means custom bandwidth/SF/CR values are used, which may not match the rest of the mesh.',
      fix: lora.usePreset ? null : [
        'Go to Settings > LoRa',
        'Enable "Use Preset"',
        'Save and reboot'
      ]
    });

    // Frequency Slot
    const isSlotMatch = lora.channelNum === rec.channelNum;
    checks.push({
      status: isSlotMatch ? 'pass' : 'fail',
      title: 'Frequency Slot',
      detail: isSlotMatch
        ? `Correctly set to slot ${rec.channelNum}`
        : `Should be slot ${rec.channelNum} for ${region === 'metro' ? 'metro' : 'rural'} areas`,
      current: String(lora.channelNum || 0),
      expected: String(rec.channelNum),
      settingKey: 'lora.channelNum',
      why: `The AZ community uses frequency slot ${rec.channelNum} to ensure all nodes can communicate on the same frequency.`,
      fix: isSlotMatch ? null : [
        'Go to Settings > LoRa',
        `Set Channel Number (Frequency Slot) to ${rec.channelNum}`,
        'Make sure Frequency Override is disabled (set to 0)',
        'Save and reboot'
      ]
    });

    // Frequency Override
    const hasOverride = lora.overrideFrequency && lora.overrideFrequency > 0;
    checks.push({
      status: hasOverride ? 'fail' : 'pass',
      title: 'Frequency Override',
      detail: hasOverride
        ? `Override is set to ${lora.overrideFrequency} MHz — this overrides the frequency slot!`
        : 'Disabled (using standard frequency slot)',
      current: hasOverride ? `${lora.overrideFrequency} MHz` : 'Disabled',
      expected: 'Disabled',
      settingKey: 'lora.overrideFrequency',
      why: 'Frequency override bypasses the channel/slot system. Unless you are a licensed HAM operator on a specific frequency, this should be disabled.',
      fix: hasOverride ? [
        'Go to Settings > LoRa',
        'Set Override Frequency to 0 (disabled)',
        'Save and reboot'
      ] : null
    });

    // OK to MQTT
    checks.push({
      status: lora.configOkToMqtt ? 'pass' : 'fail',
      title: 'OK to MQTT',
      detail: lora.configOkToMqtt
        ? 'Enabled — your packets can be relayed via MQTT'
        : 'Disabled — your packets will NOT be relayed via MQTT',
      current: lora.configOkToMqtt ? 'Enabled' : 'Disabled',
      expected: 'Enabled',
      settingKey: 'lora.configOkToMqtt',
      why: 'The AZ mesh relies on MQTT to bridge distant nodes. With this disabled, your packets cannot be forwarded via MQTT gateways.',
      fix: lora.configOkToMqtt ? null : [
        'Go to Settings > LoRa',
        'Enable "OK to MQTT" (also labeled "config_ok_to_mqtt")',
        'Save and reboot'
      ]
    });

    return { title: 'LoRa Radio Settings', icon: '\u{1F4E1}', checks };
  }

  function checkChannels(config) {
    const channels = config.channels || [];
    const checks = [];

    if (channels.length === 0) {
      checks.push({
        status: 'info',
        title: 'Channel Data',
        detail: 'No channel information found in this config export. Channel checks require a config that includes channel data (e.g., Android .cfg export with channel URL).',
        current: null, expected: null, why: null, fix: null, settingKey: null
      });
      return { title: 'Channel Configuration', icon: '\u{1F4E2}', checks };
    }

    const primary = channels.find(ch => ch.role === 1) || channels[0];

    // Primary channel name
    const nameStr = primary.name || '';
    const allowedNames = ['', 'MediumFast', 'LongFast', 'Medium-Fast', 'Long-Fast'];
    const isNameOk = allowedNames.includes(nameStr);
    checks.push({
      status: isNameOk ? 'pass' : 'warn',
      title: 'Primary Channel Name',
      detail: isNameOk 
        ? (nameStr ? `Set to "${nameStr}"` : 'Using default (empty name)') 
        : `Set to "${nameStr}", which may indicate a private channel.`,
      current: nameStr || '(default)',
      expected: 'Blank, MediumFast, or LongFast',
      settingKey: null,
      why: 'The primary channel name should match standard public names. Custom names often indicate a private channel.',
      fix: isNameOk ? null : [
        'Go to Settings > Channels',
        'Select the primary channel',
        'Clear the name or set it to your preset name',
        'Save'
      ]
    });

    // Primary channel encryption
    const pskStr = pskDisplay(primary.psk);
    const hasCustomKey = primary.psk && (
      (primary.psk instanceof Uint8Array || Array.isArray(primary.psk))
        ? (primary.psk.length > 1 || (primary.psk.length === 1 && primary.psk[0] > 1))
        : (typeof primary.psk === 'string' && primary.psk !== '' && primary.psk !== 'AQ==' && primary.psk !== 'AQ')
    );
    const isDefaultKey = primary.psk && (
      (primary.psk instanceof Uint8Array || Array.isArray(primary.psk))
        ? (primary.psk.length === 1 && primary.psk[0] === 1)
        : (primary.psk === 'AQ==' || primary.psk === 'AQ')
    );

    if (hasCustomKey) {
      checks.push({
        status: 'warn',
        title: 'Primary Channel Encryption',
        detail: 'A custom encryption key is set on the primary channel.',
        current: pskStr,
        expected: 'Default key (AQ==)',
        settingKey: null,
        why: 'The primary channel (channel 0) should be the public channel so that anyone can read/write to it. Private keys should be placed on secondary channels.',
        fix: [
          'Go to Settings > Channels',
          'Select the primary channel',
          'Clear the PSK to use the default key (AQ==)',
          'Save'
        ]
      });
    } else if (isDefaultKey) {
      checks.push({
        status: 'pass',
        title: 'Primary Channel Encryption',
        detail: 'Using the default encryption key (public channel).',
        current: pskStr,
        expected: 'Default key (AQ==)',
        settingKey: null,
        why: null, fix: null
      });
    } else {
      checks.push({
        status: 'pass',
        title: 'Primary Channel Encryption',
        detail: 'No encryption key set (public channel).',
        current: pskStr,
        expected: 'Default key (AQ==)',
        settingKey: null,
        why: null,
        fix: null
      });
    }

    return { title: 'Channel Configuration', icon: '\u{1F4E2}', checks };
  }

  function checkMQTT(config) {
    const mqtt = config.moduleConfig.mqtt;
    const rec = MQTT_RECOMMENDATIONS;
    const checks = [];

    // MQTT Enabled
    checks.push({
      status: mqtt.enabled ? 'pass' : 'info',
      title: 'MQTT Module',
      detail: mqtt.enabled
        ? 'MQTT is enabled'
        : 'MQTT is disabled. Enable it to connect to the AZ mesh MQTT broker.',
      current: mqtt.enabled ? 'Enabled' : 'Disabled',
      expected: 'Enabled (recommended)',
      settingKey: null,
      why: 'MQTT bridges your node to the wider Arizona mesh network, allowing communication with nodes beyond direct LoRa range.',
      fix: mqtt.enabled ? null : [
        'Go to Settings > Modules > MQTT',
        'Enable MQTT',
        'Configure server, username, and password as shown below',
        'Save and reboot'
      ]
    });

    if (!mqtt.enabled) {
      return { title: 'MQTT Configuration', icon: '\u{1F310}', checks };
    }

    // MQTT Server — compared by hash so the broker host isn't shipped in source.
    const serverMatch = !!mqtt.address && sha256Hex(mqtt.address) === rec.addressHash;
    checks.push({
      status: serverMatch ? 'pass' : 'warn',
      title: 'MQTT Server',
      detail: serverMatch
        ? `Connected to ${rec.addressLabel}`
        : mqtt.address ? `Connected to ${mqtt.address} (does not match the AZ mesh broker)` : 'Using default Meshtastic MQTT server',
      current: mqtt.address || '(default: mqtt.meshtastic.org)',
      expected: rec.addressLabel,
      settingKey: 'mqtt.address',
      why: 'The AZ community runs its own MQTT broker for better regional coverage and reliability. Get the broker address from the AZ Meshtastic Discord (#getting-started) or the azmsh.net Recommended Settings page.',
      fix: serverMatch ? null : [
        'Go to Settings > Modules > MQTT',
        'Set the Server Address to the AZ mesh broker (see #getting-started or azmsh.net)',
        'Save'
      ]
    });

    // MQTT Username — compared by hash (cred not stored in source).
    const userMatch = !!mqtt.username && sha256Hex(mqtt.username) === rec.usernameHash;
    checks.push({
      status: userMatch ? 'pass' : 'warn',
      title: 'MQTT Username',
      detail: userMatch
        ? 'Correct AZ mesh username'
        : `Current: "${mqtt.username || '(empty)'}"`,
      current: mqtt.username || '(empty)',
      expected: 'AZ community username',
      settingKey: 'mqtt.username',
      why: 'Join the AZ Meshtastic Discord (#getting-started) for the MQTT broker credentials.',
      fix: userMatch ? null : [
        'Go to Settings > Modules > MQTT',
        `Set Username to community username`,
        'Save'
      ]
    });

    // MQTT Password — compared by hash (cred not stored in source).
    const passMatch = !!mqtt.password && sha256Hex(mqtt.password) === rec.passwordHash;
    checks.push({
      status: passMatch ? 'pass' : 'warn',
      title: 'MQTT Password',
      detail: passMatch
        ? 'Correct AZ mesh password'
        : 'Password does not match AZ community credentials',
      current: mqtt.password ? '(set)' : '(empty)',
      expected: 'AZ community password',
      settingKey: 'mqtt.password',
      why: 'Join the AZ Meshtastic Discord (#getting-started) for the MQTT broker credentials.',
      fix: passMatch ? null : [
        'Go to Settings > Modules > MQTT',
        `Set Password to community password`,
        'Save'
      ]
    });

    // MQTT Root Topic
    const topicPattern = /^msh\/US\/AZ\/[a-zA-Z0-9_-]+$/;
    const rootOk = mqtt.root && topicPattern.test(mqtt.root);
    checks.push({
      status: rootOk ? 'pass' : 'warn',
      title: 'MQTT Topic Root',
      detail: rootOk
        ? `Topic: ${mqtt.root}`
        : `Should be "msh/US/AZ/<city>" (e.g., msh/US/AZ/Phoenix)`,
      current: mqtt.root || '(default: msh)',
      expected: `msh/US/AZ/<city>`,
      settingKey: 'mqtt.root',
      why: 'Using the correct topic hierarchy ensures your node appears in the AZ regional MQTT feed. The city should be the nearest population center (e.g., Tucson metro uses Tucson, not Marana).',
      fix: rootOk ? null : [
        'Go to Settings > Modules > MQTT',
        `Set Root Topic to: msh/US/AZ/<YourCity>`,
        'Save'
      ]
    });

    // Check channel uplink/downlink from channels if available
    const channels = config.channels || [];
    const primary = channels.find(ch => ch.role === 1) || channels[0];
    if (primary) {
      checks.push({
        status: primary.uplinkEnabled ? 'pass' : 'warn',
        title: 'Channel Uplink',
        detail: primary.uplinkEnabled
          ? 'Uplink enabled on primary channel'
          : 'Uplink is OFF on primary channel. MQTT will not forward your mesh packets.',
        current: primary.uplinkEnabled ? 'ON' : 'OFF',
        expected: 'ON',
        settingKey: null,
        why: 'Uplink sends packets from your local mesh to the MQTT broker.',
        fix: primary.uplinkEnabled ? null : [
          'Go to Settings > Channels',
          'Select the primary channel',
          'Enable Uplink',
          'Save'
        ]
      });

      checks.push({
        status: !primary.downlinkEnabled ? 'pass' : 'warn',
        title: 'Channel Downlink',
        detail: !primary.downlinkEnabled
          ? 'Downlink correctly OFF'
          : 'Downlink is ON. This will forward MQTT messages to your local mesh, which can cause congestion.',
        current: primary.downlinkEnabled ? 'ON' : 'OFF',
        expected: 'OFF',
        settingKey: null,
        why: 'Downlink floods MQTT traffic onto the local LoRa mesh. In most cases this should be OFF to prevent congestion.',
        fix: !primary.downlinkEnabled ? null : [
          'Go to Settings > Channels',
          'Select the primary channel',
          'Disable Downlink',
          'Save'
        ]
      });
    }

    // Map Report — only check if MQTT is enabled
    if (mqtt.mapReportingEnabled) {
      const interval = mqtt.mapReportSettings ? mqtt.mapReportSettings.publishIntervalSecs : 0;
      checks.push({
        status: 'pass',
        title: 'Map Reporting',
        detail: `Enabled, publishing every ${fmtSeconds(interval)}`,
        current: fmtSeconds(interval),
        expected: null,
        settingKey: 'mqtt.mapReportInterval',
        why: null, fix: null
      });
    } else {
      checks.push({
        status: 'info',
        title: 'Map Reporting',
        detail: 'Map reporting is disabled. Enable it to show your node on map.azmsh.net.',
        current: 'Disabled',
        expected: 'Enabled (recommended)',
        settingKey: null,
        why: 'Map reporting publishes your node location to the community map.',
        fix: [
          'Go to Settings > Modules > MQTT',
          'Enable "Map Reporting"',
          'Set a publish interval (e.g., 3600s for stationary, 3600s for mobile)',
          'Save'
        ]
      });
    }

    return { title: 'MQTT Configuration', icon: '\u{1F310}', checks };
  }

  function checkNodeRole(config) {
    const role = config.config.device.role;
    const name = roleName(role);
    const checks = [];
    const isRecommended = RECOMMENDED_ROLES.includes(name);

    checks.push({
      status: isRecommended ? 'pass' : 'warn',
      title: 'Node Role',
      detail: isRecommended
        ? `${name} — ${ROLE_GUIDANCE[name] || ''}`
        : `${name} is not a standard AZ community role`,
      current: name,
      expected: RECOMMENDED_ROLES.join(', '),
      settingKey: 'device.role',
      why: 'The AZ community recommends specific roles:\n' +
           Object.entries(ROLE_GUIDANCE).map(([r, d]) => `  - ${r}: ${d}`).join('\n'),
      fix: isRecommended ? null : [
        'Go to Settings > Device',
        'Set Role to one of: ' + RECOMMENDED_ROLES.join(', '),
        'CLIENT for rooftop home nodes',
        'CLIENT_MUTE for mobile/handheld',
        'ROUTER for mountain-top/high-elevation',
        'ROUTER_LATE for experimental rooftop installs',
        'Save and reboot'
      ]
    });

    return { title: 'Node Role', icon: '\u{1F4BB}', checks };
  }

  function checkBroadcastIntervals(config, nodeType) {
    const device = config.config.device;
    const position = config.config.position;
    const telemetry = config.moduleConfig.telemetry;
    const mqtt = config.moduleConfig.mqtt;
    const rec = nodeType === 'mobile' ? BROADCAST_MOBILE : BROADCAST_STATIONARY;
    const checks = [];

    // Node Info Broadcast
    const nodeInfoSecs = device.nodeInfoBroadcastSecs;
    const nodeInfoOk = nodeInfoSecs >= rec.nodeInfoBroadcastSecs;
    checks.push({
      status: nodeInfoOk ? 'pass' : 'warn',
      title: 'Node Info Broadcast Interval',
      detail: nodeInfoOk
        ? `Set to ${fmtSeconds(nodeInfoSecs)} (at or above recommended ${fmtSeconds(rec.nodeInfoBroadcastSecs)})`
        : `Set to ${fmtSeconds(nodeInfoSecs)}, recommended ${fmtSeconds(rec.nodeInfoBroadcastSecs)} minimum`,
      current: fmtSeconds(nodeInfoSecs),
      expected: fmtSeconds(rec.nodeInfoBroadcastSecs),
      settingKey: 'device.nodeInfoBroadcastSecs',
      why: 'Broadcasting node info too often creates unnecessary traffic. 12 hours is sufficient for the mesh to know about your node.',
      fix: nodeInfoOk ? null : [
        'Go to Settings > Device',
        `Set Node Info Broadcast Seconds to ${rec.nodeInfoBroadcastSecs} (12 hours)`,
        'Save'
      ]
    });

    // Smart Position Broadcast (mobile)
    if (nodeType === 'mobile') {
      const smartOn = position.positionBroadcastSmartEnabled;
      checks.push({
        status: smartOn ? 'pass' : 'warn',
        title: 'Smart Position Broadcast',
        detail: smartOn
          ? 'Enabled — position updates triggered by movement'
          : 'Disabled — consider enabling for mobile nodes',
        current: smartOn ? 'ON' : 'OFF',
        expected: 'ON',
        settingKey: 'position.positionBroadcastSmartEnabled',
        why: 'Smart broadcast sends position updates only when you move, reducing unnecessary airtime while keeping your location current.',
        fix: smartOn ? null : [
          'Go to Settings > Position',
          'Enable "Smart Position Broadcast"',
          `Set Minimum Distance to ${rec.smartMinDistance}m`,
          `Set Minimum Interval to ${rec.smartMinInterval}s`,
          'Save'
        ]
      });

      // Smart broadcast params
      if (smartOn) {
        const distOk = position.broadcastSmartMinimumDistance >= rec.smartMinDistance;
        checks.push({
          status: distOk ? 'pass' : 'info',
          title: 'Smart Broadcast Min Distance',
          current: `${position.broadcastSmartMinimumDistance || 0}m`,
          expected: `${rec.smartMinDistance}m`,
          detail: `Set to ${position.broadcastSmartMinimumDistance || 0}m (recommended: ${rec.smartMinDistance}m)`,
          settingKey: 'position.broadcastSmartMinimumDistance',
          why: null, fix: null
        });

        const intOk = position.broadcastSmartMinimumIntervalSecs >= rec.smartMinInterval;
        checks.push({
          status: intOk ? 'pass' : 'info',
          title: 'Smart Broadcast Min Interval',
          current: `${position.broadcastSmartMinimumIntervalSecs || 0}s`,
          expected: `${rec.smartMinInterval}s`,
          detail: `Set to ${position.broadcastSmartMinimumIntervalSecs || 0}s (recommended: ${rec.smartMinInterval}s)`,
          settingKey: 'position.broadcastSmartMinimumIntervalSecs',
          why: null, fix: null
        });
      }
    } else {
      // Stationary: smart broadcast should be off
      if (position.positionBroadcastSmartEnabled) {
        checks.push({
          status: 'info',
          title: 'Smart Position Broadcast',
          detail: 'Enabled, but not needed for stationary nodes (fixed position nodes do not move).',
          current: 'ON',
          expected: 'OFF (stationary)',
          settingKey: 'position.positionBroadcastSmartEnabled',
          why: 'Stationary nodes have a fixed position and do not need movement-triggered updates.',
          fix: [
            'Go to Settings > Position',
            'Disable "Smart Position Broadcast" for stationary nodes',
            'Save'
          ]
        });
      } else {
        checks.push({
          status: 'pass',
          title: 'Smart Position Broadcast',
          detail: 'Correctly disabled for stationary node',
          current: 'OFF',
          expected: 'OFF',
          settingKey: null,
          why: null, fix: null
        });
      }
    }

    // Position Broadcast Interval
    const posSecs = position.positionBroadcastSecs;
    const posOk = posSecs >= rec.positionBroadcastSecs;
    checks.push({
      status: posOk ? 'pass' : 'warn',
      title: 'Position Broadcast Interval',
      detail: posOk
        ? `Set to ${fmtSeconds(posSecs)} (meets recommended ${fmtSeconds(rec.positionBroadcastSecs)})`
        : `Set to ${fmtSeconds(posSecs)}, recommended at least ${fmtSeconds(rec.positionBroadcastSecs)}`,
      current: fmtSeconds(posSecs),
      expected: fmtSeconds(rec.positionBroadcastSecs),
      settingKey: 'position.positionBroadcastSecs',
      why: nodeType === 'mobile'
        ? 'For mobile nodes, 1 hour is a good fallback interval when smart broadcast is active.'
        : 'Stationary nodes only need to broadcast position every 12 hours.',
      fix: posOk ? null : [
        'Go to Settings > Position',
        `Set Position Broadcast Seconds to ${rec.positionBroadcastSecs}`,
        'Save'
      ]
    });

    // GPS Update Interval
    const gpsSecs = position.gpsUpdateInterval;
    const gpsOk = gpsSecs >= rec.gpsUpdateInterval || gpsSecs === 0;
    checks.push({
      status: gpsOk ? 'pass' : 'warn',
      title: 'GPS Update Interval',
      detail: gpsOk
        ? `Set to ${fmtSeconds(gpsSecs)}`
        : `Set to ${fmtSeconds(gpsSecs)}, recommended ${fmtSeconds(rec.gpsUpdateInterval)}`,
      current: fmtSeconds(gpsSecs),
      expected: fmtSeconds(rec.gpsUpdateInterval),
      settingKey: 'position.gpsUpdateInterval',
      why: nodeType === 'mobile'
        ? 'GPS polling every 5 minutes balances battery and position accuracy for mobile.'
        : 'Stationary nodes rarely need GPS updates — 6 hours is sufficient.',
      fix: gpsOk ? null : [
        'Go to Settings > Position',
        `Set GPS Update Interval to ${rec.gpsUpdateInterval}`,
        'Save'
      ]
    });

    // Device Metrics Interval
    const devMetrics = telemetry.deviceUpdateInterval;
    const devOk = devMetrics > 0 && devMetrics >= rec.deviceMetricsInterval;
    checks.push({
      status: devOk ? 'pass' : 'warn',
      title: 'Device Metrics Interval',
      detail: devOk
        ? `Set to ${fmtSeconds(devMetrics)}`
        : `Set to ${fmtSeconds(devMetrics)}, recommended ${fmtSeconds(rec.deviceMetricsInterval)}`,
      current: fmtSeconds(devMetrics),
      expected: fmtSeconds(rec.deviceMetricsInterval),
      settingKey: 'telemetry.deviceUpdateInterval',
      why: 'Device metrics (battery, voltage, etc.) every hour is sufficient for monitoring.',
      fix: devOk ? null : [
        'Go to Settings > Modules > Telemetry',
        `Set Device Update Interval to ${rec.deviceMetricsInterval}`,
        'Save'
      ]
    });

    // Map Report Interval — only check if MQTT is enabled
    if (mqtt.enabled && mqtt.mapReportingEnabled && mqtt.mapReportSettings) {
      const mapSecs = mqtt.mapReportSettings.publishIntervalSecs || 0;
      const mapOk = mapSecs >= rec.mapReportInterval || mapSecs === 0;
      checks.push({
        status: mapOk ? 'pass' : 'warn',
        title: 'Map Report Interval',
        detail: mapOk
          ? `Set to ${fmtSeconds(mapSecs)}`
          : `Set to ${fmtSeconds(mapSecs)}, recommended ${fmtSeconds(rec.mapReportInterval)}`,
        current: fmtSeconds(mapSecs),
        expected: fmtSeconds(rec.mapReportInterval),
        settingKey: 'mqtt.mapReportInterval',
        why: null,
        fix: mapOk ? null : [
          'Go to Settings > Modules > MQTT > Map Report Settings',
          `Set Publish Interval to ${rec.mapReportInterval}`,
          'Save'
        ]
      });
    }
    // If MQTT is disabled, skip map report interval check entirely (Feature #4)

    return { title: 'Broadcast Intervals', icon: '\u{23F1}\u{FE0F}', checks };
  }

  function checkNeighborInfo(config, nodeType) {
    const checks = [];
    const neighborInfo = config.moduleConfig.neighborInfo || {};
    const rec = NEIGHBORINFO_RECOMMENDATIONS;

    // Only check for stationary nodes
    if (nodeType !== 'stationary') {
      checks.push({
        status: 'info',
        title: 'NeighborInfo Module',
        detail: 'NeighborInfo is primarily for stationary nodes. Mobile nodes do not need this.',
        current: 'N/A',
        expected: null,
        settingKey: null,
        why: null, fix: null
      });
      return { title: 'NeighborInfo', icon: '\u{1F4CA}', checks };
    }

    // Enabled
    const isEnabled = neighborInfo.enabled === true;
    checks.push({
      status: isEnabled ? 'pass' : 'fail',
      title: 'NeighborInfo Enabled',
      detail: isEnabled
        ? 'NeighborInfo module is enabled'
        : 'NeighborInfo module is disabled. Enable it for stationary nodes.',
      current: isEnabled ? 'Enabled' : 'Disabled',
      expected: 'Enabled',
      settingKey: 'neighborInfo.enabled',
      why: 'NeighborInfo helps the mesh understand network topology by sharing which nodes can hear each other.',
      fix: isEnabled ? null : [
        'Go to Settings > Modules > Neighbor Info',
        'Enable the NeighborInfo module',
        'Save'
      ]
    });

    // Transmit over LoRa
    const transmitOverLora = neighborInfo.transmitOverLora === true;
    checks.push({
      status: transmitOverLora ? 'pass' : (isEnabled ? 'fail' : 'info'),
      title: 'Transmit NeighborInfo over LoRa',
      detail: transmitOverLora
        ? 'NeighborInfo is transmitted over LoRa'
        : 'NeighborInfo is NOT transmitted over LoRa.',
      current: transmitOverLora ? 'Enabled' : 'Disabled',
      expected: 'Enabled',
      settingKey: 'neighborInfo.transmitOverLora',
      why: 'Transmitting over LoRa allows all mesh nodes to build a more complete picture of the network.',
      fix: transmitOverLora ? null : [
        'Go to Settings > Modules > Neighbor Info',
        'Enable "Transmit over LoRa"',
        'Save'
      ]
    });

    // Update Interval
    const interval = neighborInfo.updateInterval || 0;
    const intervalOk = interval >= rec.updateInterval || interval === 0;
    checks.push({
      status: intervalOk ? 'pass' : 'warn',
      title: 'NeighborInfo Update Interval',
      detail: intervalOk
        ? `Set to ${fmtSeconds(interval)} (meets recommended ${fmtSeconds(rec.updateInterval)})`
        : `Set to ${fmtSeconds(interval)}, recommended ${fmtSeconds(rec.updateInterval)} (11 hours)`,
      current: fmtSeconds(interval),
      expected: fmtSeconds(rec.updateInterval),
      settingKey: 'neighborInfo.updateInterval',
      why: 'NeighborInfo does not need to broadcast frequently. 11 hours minimizes airtime while keeping data fresh.',
      fix: intervalOk ? null : [
        'Go to Settings > Modules > Neighbor Info',
        `Set Update Interval to ${rec.updateInterval} (11 hours)`,
        'Save'
      ]
    });

    return { title: 'NeighborInfo', icon: '\u{1F4CA}', checks };
  }

  function checkFirmware(config) {
    const checks = [];
    const fw = config.firmwareVersion;

    if (!fw) {
      checks.push({
        status: 'info',
        title: 'Firmware Version',
        detail: 'Firmware version not found in this config export. Binary (.cfg) exports typically include this; YAML/JSON exports may not.',
        current: null, expected: null, why: null, fix: null, settingKey: null
      });
      return { title: 'Firmware', icon: '\u{1F4BE}', checks };
    }

    // Parse version — could be a string like "2.6.6.abcdef" or numeric
    let versionStr = '';
    let numericVersion = 0;

    if (typeof fw === 'string') {
      versionStr = fw.replace(/^v/i, '');
      const parts = versionStr.split('.');
      if (parts.length >= 3) {
        numericVersion = (parseInt(parts[0]) || 0) * 10000 +
                         (parseInt(parts[1]) || 0) * 100 +
                         (parseInt(parts[2]) || 0);
      }
    } else if (typeof fw === 'number' && fw > 0) {
      // Numeric version from protobuf (e.g., 20606 for 2.6.6)
      numericVersion = fw;
      const major = Math.floor(fw / 10000);
      const minor = Math.floor((fw % 10000) / 100);
      const patch = fw % 100;
      versionStr = `${major}.${minor}.${patch}`;
    }

    if (numericVersion === 0 && versionStr === '') {
      checks.push({
        status: 'info',
        title: 'Firmware Version',
        detail: 'Could not parse firmware version from config.',
        current: String(fw), expected: null, why: null, fix: null, settingKey: null
      });
      return { title: 'Firmware', icon: '\u{1F4BE}', checks };
    }

    const isUpToDate = numericVersion >= LATEST_FIRMWARE.numericMin;

    checks.push({
      status: isUpToDate ? 'pass' : 'warn',
      title: 'Firmware Version',
      detail: isUpToDate
        ? `Running ${versionStr} (latest stable: ${LATEST_FIRMWARE.version})`
        : `Running ${versionStr} \u2014 update available (${LATEST_FIRMWARE.version})`,
      current: versionStr,
      expected: LATEST_FIRMWARE.version + ' or newer',
      settingKey: null,
      why: isUpToDate ? null : 'Keeping firmware up to date ensures you have the latest bug fixes, security patches, and mesh protocol improvements.',
      fix: isUpToDate ? null : [
        `Visit ${LATEST_FIRMWARE.flasherUrl} in Chrome or Edge`,
        'Connect your node via USB',
        'Select your device and flash the latest stable firmware',
        'After flashing, re-import your config or re-apply settings'
      ]
    });

    return { title: 'Firmware', icon: '\u{1F4BE}', checks };
  }

  // ---- Public API ----

  export const ConfigChecker = {
    /**
     * Dynamically update the latest firmware value at runtime
     */
    setLatestFirmware(version, numericMin) {
      if (version) LATEST_FIRMWARE.version = version;
      if (numericMin) LATEST_FIRMWARE.numericMin = numericMin;
    },

    /**
     * Run all checks against the parsed config.
     *
     * @param {Object} config - Normalized config from ConfigParser
     * @param {string} region - 'metro' or 'rural'
     * @param {string} nodeType - 'mobile' or 'stationary'
     * @returns {{ categories: Array, score: number, total: number, passed: number, failed: number, warnings: number }}
     */
    check(config, region, nodeType) {
      const categories = [
        checkFirmware(config),
        checkLoRa(config, region),
        checkChannels(config),
        checkMQTT(config),
        checkNodeRole(config),
        checkBroadcastIntervals(config, nodeType),
        checkNeighborInfo(config, nodeType),
      ];

      // Calculate score
      let total = 0;
      let passed = 0;
      let failed = 0;
      let warnings = 0;

      for (const cat of categories) {
        for (const check of cat.checks) {
          if (check.status === 'info') continue;  // info items don't count
          total++;
          if (check.status === 'pass') passed++;
          else if (check.status === 'fail') failed++;
          else if (check.status === 'warn') warnings++;
        }
      }

      const score = total > 0 ? Math.round((passed / total) * 100) : 0;

      return { categories, score, total, passed, failed, warnings };
    }
  };
