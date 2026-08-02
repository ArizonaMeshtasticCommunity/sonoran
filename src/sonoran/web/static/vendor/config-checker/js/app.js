/**
 * app.js — Main application logic for Arizona Meshtastic Config Checker
 *
 * Handles file upload, UI interactions, results rendering, config fix/export,
 * report export, Web Serial device connection, editable settings, optional
 * MQTT configuration, and new node builder.
 */

import { ConfigParser } from './parser.js';
import { ConfigChecker } from './checker.js';
import { ConfigFixer } from './fixer.js';
import { diagnostics, STEPS } from './diagnostics.js';

// ---- Time Utility Functions ----

/**
 * Parse a human-readable time string into seconds.
 * Supports: plain numbers (seconds), Nm/Nmin (minutes), Nh/Nhr (hours), Nd (days).
 * Decimals like 1.5h are supported.
 */
function parseTimeInput(str) {
  if (str == null) return NaN;
  const s = String(str).trim().toLowerCase();
  if (s === '') return NaN;

  // Match number + optional unit
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
 * Format seconds into a human-readable string.
 * E.g., 3600 → "1 hour", 39600 → "11 hours", 1800 → "30 minutes"
 */
function formatSeconds(seconds) {
  if (seconds == null || seconds === 0) return '0 seconds';
  const s = Number(seconds);
  if (isNaN(s) || s <= 0) return '0 seconds';

  if (s >= 86400 && s % 86400 === 0) {
    const d = s / 86400;
    return d === 1 ? '1 day' : `${d} days`;
  }
  if (s >= 86400) {
    const d = (s / 86400);
    return `${d % 1 === 0 ? d : d.toFixed(1)} days`;
  }
  if (s >= 3600 && s % 3600 === 0) {
    const h = s / 3600;
    return h === 1 ? '1 hour' : `${h} hours`;
  }
  if (s >= 3600) {
    const h = (s / 3600);
    return `${h % 1 === 0 ? h : h.toFixed(1)} hours`;
  }
  if (s >= 60 && s % 60 === 0) {
    const m = s / 60;
    return m === 1 ? '1 minute' : `${m} minutes`;
  }
  if (s >= 60) {
    const m = (s / 60);
    return `${m % 1 === 0 ? m : m.toFixed(1)} minutes`;
  }
  return s === 1 ? '1 second' : `${s} seconds`;
}

// ---- Setting Type Metadata ----

/**
 * Defines the input type for known setting keys.
 * 'select' = dropdown, 'toggle' = on/off switch, 'time' = time input, 'number' = plain number
 */
const SETTING_TYPES = {
  'device.role': {
    type: 'select',
    options: [
      { value: 'CLIENT', label: 'CLIENT - Most nodes' },
      { value: 'CLIENT_MUTE', label: 'CLIENT_MUTE - Pocket nodes or weak antenna' },
      { value: 'CLIENT_BASE', label: 'CLIENT_BASE - Rebroadcast traffic to/from favorited nodes' }
    ]
  },
  'lora.modemPreset': {
    type: 'select',
    options: Object.entries(ConfigParser.MODEM_PRESET_NAMES).map(([num, name]) => ({
      value: name, label: name.replace(/_/g, ' ')
    }))
  },
  'lora.channelNum': { type: 'number' },
  'lora.usePreset': { type: 'toggle' },
  'lora.configOkToMqtt': { type: 'toggle' },
  'lora.overrideFrequency': { type: 'number' },
  'lora.hopLimit': {
    type: 'select',
    options: [
      { value: '1', label: '1' },
      { value: '2', label: '2' },
      { value: '3', label: '3 (recommended)' },
      { value: '4', label: '4' },
      { value: '5', label: '5' },
      { value: '6', label: '6' },
      { value: '7', label: '7 (max)' },
    ]
  },
  'device.nodeInfoBroadcastSecs': { type: 'time' },
  'position.positionBroadcastSecs': { type: 'time' },
  'position.positionBroadcastSmartEnabled': { type: 'toggle' },
  'position.broadcastSmartMinimumDistance': { type: 'number' },
  'position.broadcastSmartMinimumIntervalSecs': { type: 'time' },
  'position.gpsUpdateInterval': { type: 'time' },
  'telemetry.deviceUpdateInterval': { type: 'time' },
  'neighborInfo.enabled': { type: 'toggle' },
  'neighborInfo.transmitOverLora': { type: 'toggle' },
  'neighborInfo.updateInterval': { type: 'time' },
  'mqtt.address': { type: 'text' },
  'mqtt.username': { type: 'text' },
  'mqtt.password': { type: 'text' },
  'mqtt.root': { type: 'text' },
  'mqtt.mapReportInterval': { type: 'time' },
};

// ---- DOM References ----
  const uploadArea = document.getElementById('uploadArea');
  const fileInput = document.getElementById('fileInput');
  const fileInfo = document.getElementById('fileInfo');
  const resultsSection = document.getElementById('resultsSection');
  const healthScoreContainer = document.getElementById('healthScoreContainer');
  const resultsContainer = document.getElementById('resultsContainer');
  const bottomActionBar = document.getElementById('bottomActionBar');
  const autoFixBtn = document.getElementById('autoFixBtn');
  const exportReportBtn = document.getElementById('exportReportBtn');

  // Web Serial DOM
  const serialConnectBtn = document.getElementById('serialConnectBtn');
  const serialReadBtn = document.getElementById('serialReadBtn');
  const serialApplyBtn = document.getElementById('serialApplyBtn');
  const serialStatus = document.getElementById('serialStatus');
  const serialNotSupported = document.getElementById('serialNotSupported');

  // Diagnostics DOM
  const diagReportBar = document.getElementById('diagReportBar');
  const copyDiagBtn = document.getElementById('copyDiagBtn');
  const viewDiagBtn = document.getElementById('viewDiagBtn');
  const diagReportText = document.getElementById('diagReportText');
  const diagCopyStatus = document.getElementById('diagCopyStatus');

  // New Node Builder DOM
  const newNodeBtn = document.getElementById('newNodeBtn');
  const newNodeFormSection = document.getElementById('newNodeFormSection');
  const buildNewConfigBtn = document.getElementById('buildNewConfigBtn');
  const newLongName = document.getElementById('newLongName');
  const newShortName = document.getElementById('newShortName');
  const newRole = document.getElementById('newRole');
  const newHopLimit = document.getElementById('newHopLimit');

  // MQTT Config DOM
  const mqttConfigTemplate = document.getElementById('mqttConfigTemplate');
  const mqttConfigBody = document.getElementById('mqttConfigBody');
  const mqttEnableToggle = document.getElementById('mqttEnableToggle');
  const mqttFields = document.getElementById('mqttFields');
  const mqttServer = document.getElementById('mqttServer');
  const mqttUsername = document.getElementById('mqttUsername');
  const mqttPassword = document.getElementById('mqttPassword');
  const mqttCity = document.getElementById('mqttCity');
  const mqttProxyToggle = document.getElementById('mqttProxyToggle');
  const mqttMapReportToggle = document.getElementById('mqttMapReportToggle');
  const mqttMapInterval = document.getElementById('mqttMapInterval');
  const mqttMapIntervalRow = document.getElementById('mqttMapIntervalRow');

  // ---- State ----
  let currentConfig = null;
  let currentReport = null;
  let currentFilename = null;
  let serialPort = null;
  let isNewNodeConfig = false;
  let userOverrides = {};  // Stores user-edited values by settingKey

  // ---- Privacy-safe diagnostics ----
  // recordDiag passes ONLY whitelisted metadata to the diagnostics module, which
  // itself re-whitelists + scrubs. We never pass config contents, channel names,
  // PSK/keys, or input bytes here. When an error is recorded we reveal the
  // "copy diagnostic report" control so the user can choose to share it.
  function recordDiag(ctx) {
    if (!diagnostics) return;
    try {
      diagnostics.record(ctx);
      if (diagReportBar) diagReportBar.style.display = 'block';
    } catch (e) {
      console.warn('diagnostics record failed:', e);
    }
  }

  if (copyDiagBtn) {
    copyDiagBtn.addEventListener('click', async () => {
      const report = diagnostics ? diagnostics.generateReport() : '(diagnostics unavailable)';
      let ok = false;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(report);
          ok = true;
        }
      } catch (e) { ok = false; }
      if (!ok) {
        // Fallback: reveal the text so the user can select + copy manually.
        diagReportText.textContent = report;
        diagReportText.style.display = 'block';
      }
      if (diagCopyStatus) {
        diagCopyStatus.textContent = ok ? 'Copied. No config data is included.' : 'Select the text above and copy it.';
      }
    });
  }
  if (viewDiagBtn) {
    viewDiagBtn.addEventListener('click', () => {
      const report = diagnostics ? diagnostics.generateReport() : '(diagnostics unavailable)';
      const showing = diagReportText.style.display !== 'none';
      diagReportText.textContent = report;
      diagReportText.style.display = showing ? 'none' : 'block';
    });
  }

  // ---- Web Serial Init ----
  if ('serial' in navigator) {
    serialConnectBtn.disabled = false;
  } else {
    serialConnectBtn.style.display = 'none';
    serialReadBtn.style.display = 'none';
    serialNotSupported.style.display = 'block';
  }

  // ---- File Upload Handling ----

  uploadArea.addEventListener('click', () => fileInput.click());

  uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('dragover');
  });

  uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragover');
  });

  uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      handleFile(fileInput.files[0]);
    }
  });

  // Re-run checks when region or node type changes
  document.querySelectorAll('input[name="region"], input[name="nodeType"]').forEach(el => {
    el.addEventListener('change', () => {
      if (currentConfig) {
        runChecks(currentConfig);
      }
    });
  });

  // ---- MQTT Config Toggle ----

  mqttEnableToggle.addEventListener('change', () => {
    mqttFields.style.display = mqttEnableToggle.checked ? 'block' : 'none';
  });

  mqttMapReportToggle.addEventListener('change', () => {
    mqttMapIntervalRow.style.display = mqttMapReportToggle.checked ? 'grid' : 'none';
  });

  // ---- New Node Builder ----
  newNodeBtn.addEventListener('click', () => {
    newNodeFormSection.style.display = 'block';
    newNodeFormSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  buildNewConfigBtn.addEventListener('click', () => {
    const region = document.querySelector('input[name="region"]:checked').value;
    const nodeType = document.querySelector('input[name="nodeType"]:checked').value;

    const config = ConfigFixer.buildNewConfig({
      longName: newLongName.value.trim(),
      shortName: newShortName.value.trim(),
      region,
      nodeType,
      role: newRole.value,
      hopLimit: newHopLimit.value
    });

    currentConfig = config;
    currentFilename = null;
    isNewNodeConfig = true;
    userOverrides = {};

    fileInfo.style.display = 'block';
    fileInfo.innerHTML = '<strong>New Node Config</strong> &mdash; Built from scratch with AZ community defaults';

    runChecks(config);
  });

  // ---- Action Buttons ----

  autoFixBtn.addEventListener('click', () => {
    if (!currentConfig) return;
    const region = document.querySelector('input[name="region"]:checked').value;
    const nodeType = document.querySelector('input[name="nodeType"]:checked').value;

    // Gather MQTT config from the form
    const mqttConfig = getMqttFormConfig();

    try {
      const fixedConfig = ConfigFixer.fix(currentConfig, region, nodeType, userOverrides, mqttConfig);
      const result = ConfigFixer.exportFixed(fixedConfig, currentFilename, isNewNodeConfig);

      if (result.fallbackNotice) {
        alert(result.fallbackNotice);
      }

      downloadFile(result.data, result.filename, result.mimeType);
    } catch (err) {
      console.error('Auto-fix error:', err);
      alert('Auto-fix failed: ' + err.message);
      recordDiag({ step: STEPS.FIXER, error: err, format: currentConfig && currentConfig.source });
    }
  });

  exportReportBtn.addEventListener('click', () => {
    if (!currentReport) return;
    const text = generateReportText(currentReport);
    downloadFile(text, 'config-check-report.txt', 'text/plain');
  });

  // ---- Web Serial ----

  if (serialConnectBtn) {
    serialConnectBtn.addEventListener('click', async () => {
      try {
        if (serialPort) {
          // Disconnect
          await serialPort.close();
          serialPort = null;
          serialConnectBtn.textContent = 'Connect via USB';
          serialReadBtn.disabled = true;
          serialApplyBtn.disabled = true;
          serialApplyBtn.style.display = 'none';
          setSerialStatus('Disconnected.', '');
          return;
        }

        setSerialStatus('Requesting device...', '');
        serialPort = await navigator.serial.requestPort({
          filters: [
            { usbVendorId: 0x1A86 },  // CH340/CH341
            { usbVendorId: 0x10C4 },  // CP210x (Silicon Labs)
            { usbVendorId: 0x303A },  // ESP32-S3 native USB
            { usbVendorId: 0x239A },  // Adafruit nRF52840
          ]
        });

        await serialPort.open({ baudRate: 115200 });

        serialConnectBtn.innerHTML =
          '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M13 3h-2v10h2V3zm4.83 2.17l-1.42 1.42C17.99 7.86 19 9.81 19 12c0 3.87-3.13 7-7 7s-7-3.13-7-7c0-2.19 1.01-4.14 2.58-5.42L6.17 5.17C4.23 6.82 3 9.26 3 12c0 4.97 4.03 9 9 9s9-4.03 9-9c0-2.74-1.23-5.18-3.17-6.83z"/></svg> Disconnect';
        serialReadBtn.disabled = false;
        // Show program button in the bottom bar when connected
        serialApplyBtn.style.display = 'inline-flex';
        serialApplyBtn.disabled = false;
        setSerialStatus('Connected. Use "Read Config" to pull settings from your device.', 'connected');
      } catch (err) {
        if (err.name === 'NotFoundError') {
          setSerialStatus('No device selected.', '');
        } else {
          setSerialStatus('Connection failed: ' + err.message, 'error');
          console.error('Serial connect error:', err);
          recordDiag({ step: STEPS.SERIAL_CONNECT, error: err });
        }
        serialPort = null;
      }
    });
  }

  if (serialReadBtn) {
    serialReadBtn.addEventListener('click', async () => {
      if (!serialPort) return;
      try {
        setSerialStatus('Reading config from device... (this may take a few seconds)', '');
        serialReadBtn.disabled = true;

        const configData = await readSerialConfig(serialPort);
        if (configData) {
          currentConfig = configData;
          isNewNodeConfig = false;
          userOverrides = {};
          fileInfo.style.display = 'block';
          fileInfo.innerHTML = '<strong>USB Device</strong> &mdash; Config read via Web Serial';
          runChecks(currentConfig);
          setSerialStatus('Config read successfully!', 'connected');
        } else {
          setSerialStatus('Could not read config. Make sure the device is running Meshtastic firmware.', 'error');
        }
      } catch (err) {
        setSerialStatus('Read failed: ' + err.message, 'error');
        console.error('Serial read error:', err);
        recordDiag({ step: STEPS.SERIAL_READ, error: err });
      } finally {
        serialReadBtn.disabled = false;
      }
    });
  }

  if (serialApplyBtn) {
    serialApplyBtn.addEventListener('click', async () => {
      if (!serialPort) return;
      if (!currentConfig) {
        setSerialStatus('Read or build a config first before applying changes.', 'error');
        return;
      }

      const region = document.querySelector('input[name="region"]:checked').value;
      const nodeType = document.querySelector('input[name="nodeType"]:checked').value;

      if (!confirm('This will send recommended settings to your device. The device will reboot. Continue?')) {
        return;
      }

      try {
        setSerialStatus('Applying recommended settings...', '');
        serialApplyBtn.disabled = true;

        await applySerialConfig(serialPort, region, nodeType);
        setSerialStatus('Settings applied! Device is rebooting. Reconnect in a few seconds to verify.', 'connected');

        try { await serialPort.close(); } catch (e) { /* may already be closed */ }
        serialPort = null;
        serialConnectBtn.innerHTML =
          '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M15 7v4h1v2h-3V5h2l-4-4-4 4h2v8H6v-2h1V7c0-1.1-.9-2-2-2H3v2h2v4H3v2h2v4c0 1.1.9 2 2 2h2v2h-1v2h3v-8h3v8h3v-2h-1v-2h2c1.1 0 2-.9 2-2v-4h2v-2h-2V7c0-1.1-.9-2-2-2h-2v2h2z"/></svg> Connect via USB';
        serialReadBtn.disabled = true;
        serialApplyBtn.style.display = 'none';
      } catch (err) {
        setSerialStatus('Apply failed: ' + err.message, 'error');
        console.error('Serial apply error:', err);
        recordDiag({ step: STEPS.SERIAL_APPLY, error: err });
      } finally {
        serialApplyBtn.disabled = false;
      }
    });
  }

  function setSerialStatus(msg, className) {
    serialStatus.textContent = msg;
    serialStatus.className = 'serial-status' + (className ? ' ' + className : '');
  }

  /**
   * Read config from a Meshtastic device via serial.
   */
  async function readSerialConfig(port) {
    const encoder = new TextEncoder();
    const writer = port.writable.getWriter();
    const reader = port.readable.getReader();

    try {
      await writer.write(encoder.encode('\r\n'));

      const chunks = [];
      const startTime = Date.now();
      const timeout = 5000;

      while (Date.now() - startTime < timeout) {
        const { value, done } = await Promise.race([
          reader.read(),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error('timeout')), timeout - (Date.now() - startTime))
          )
        ]).catch(() => ({ value: null, done: true }));

        if (done || !value) break;
        chunks.push(value);
      }

      if (chunks.length > 0) {
        const combined = new Uint8Array(chunks.reduce((acc, c) => acc + c.length, 0));
        let offset = 0;
        for (const chunk of chunks) {
          combined.set(chunk, offset);
          offset += chunk.length;
        }

        try {
          const text = new TextDecoder().decode(combined);
          if (text.includes(':') || text.includes('{')) {
            return await ConfigParser.parse(combined.buffer, 'serial-read.yaml');
          }
        } catch (e) {
          return await ConfigParser.parse(combined.buffer, 'serial-read.cfg');
        }
      }

      return null;
    } finally {
      reader.releaseLock();
      writer.releaseLock();
    }
  }

  /**
   * Apply recommended config to a device via serial.
   */
  async function applySerialConfig(port, region, nodeType) {
    const encoder = new TextEncoder();
    const writer = port.writable.getWriter();

    try {
      const rec = ConfigFixer.getRecommendations(region, nodeType);
      const commands = [];

      commands.push(`meshtastic --set lora.modem_preset ${rec.modemPresetName}`);
      commands.push(`meshtastic --set lora.channel_num ${rec.channelNum}`);
      commands.push(`meshtastic --set lora.use_preset true`);
      commands.push(`meshtastic --set lora.config_ok_to_mqtt true`);
      commands.push(`meshtastic --set device.node_info_broadcast_secs ${rec.nodeInfoBroadcastSecs}`);
      commands.push(`meshtastic --set position.position_broadcast_secs ${rec.positionBroadcastSecs}`);

      if (nodeType === 'mobile') {
        commands.push(`meshtastic --set position.position_broadcast_smart_enabled true`);
        commands.push(`meshtastic --set position.broadcast_smart_minimum_distance ${rec.smartMinDistance}`);
        commands.push(`meshtastic --set position.broadcast_smart_minimum_interval_secs ${rec.smartMinInterval}`);
      }

      commands.push(`meshtastic --set telemetry.device_update_interval ${rec.deviceMetricsInterval}`);

      // NeighborInfo for stationary
      if (nodeType === 'stationary') {
        commands.push(`meshtastic --set neighbor_info.enabled true`);
        commands.push(`meshtastic --set neighbor_info.transmit_over_lora true`);
        commands.push(`meshtastic --set neighbor_info.update_interval ${rec.neighborInfo.updateInterval}`);
      }

      for (const cmd of commands) {
        await writer.write(encoder.encode(cmd + '\r\n'));
        await new Promise(r => setTimeout(r, 300));
      }

      await writer.write(encoder.encode('meshtastic --reboot\r\n'));
    } finally {
      writer.releaseLock();
    }
  }

  // ---- File Processing ----

  async function handleFile(file) {
    fileInfo.style.display = 'block';
    fileInfo.textContent = `Loading: ${file.name} (${formatBytes(file.size)})...`;
    resultsSection.style.display = 'none';
    bottomActionBar.style.display = 'none';
    isNewNodeConfig = false;
    userOverrides = {};

    try {
      const buffer = await file.arrayBuffer();
      const config = await ConfigParser.parse(buffer, file.name);
      currentConfig = config;
      currentFilename = file.name;

      const sourceLabel = {
        android: 'Android .cfg (protobuf)',
        backup: 'Device backup (protobuf)',
        yaml: 'CLI YAML export',
        json: 'iOS/Web JSON export'
      }[config.source] || config.source;

      fileInfo.innerHTML =
        `<strong>${escapeHtml(file.name)}</strong> &mdash; ${formatBytes(file.size)} &mdash; Detected format: ${escapeHtml(sourceLabel)}`;

      runChecks(config);
    } catch (err) {
      fileInfo.innerHTML =
        `<strong style="color: var(--error);">Error parsing file:</strong> ${escapeHtml(err.message)}`;
      console.error('Parse error:', err);
      // Privacy-safe diagnostics: whitelisted metadata only — never file bytes,
      // never the filename (extension is derived), never config contents.
      recordDiag({
        step: STEPS.PARSE,
        error: err,
        fileName: file && file.name,
        fileSize: file && file.size,
      });
    }
  }

  // ---- Get MQTT form config ----
  function getMqttFormConfig() {
    if (!mqttEnableToggle.checked) {
      return { enabled: false };
    }
    const city = mqttCity.value.trim();
    return {
      enabled: true,
      address: mqttServer.value.trim(),
      username: mqttUsername.value.trim(),
      password: mqttPassword.value.trim(),
      root: city ? `msh/US/AZ/${city}` : '',
      proxyToClientEnabled: mqttProxyToggle.checked,
      mapReportingEnabled: mqttMapReportToggle.checked,
      mapReportInterval: parseTimeInput(mqttMapInterval.value) || 3600
    };
  }

  // ---- Run Checks & Render ----

  function runChecks(config) {
    const region = document.querySelector('input[name="region"]:checked').value;
    const nodeType = document.querySelector('input[name="nodeType"]:checked').value;

    const report = ConfigChecker.check(config, region, nodeType);
    currentReport = report;

    renderNodeInfo(config);
    renderHealthScore(report);
    renderResults(report);

    // (MQTT form is injected below)

    // Pre-fill MQTT form from config if MQTT is already configured
    if (config.moduleConfig.mqtt.enabled) {
      mqttEnableToggle.checked = true;
      mqttFields.style.display = 'block';
      if (config.moduleConfig.mqtt.address) mqttServer.value = config.moduleConfig.mqtt.address;
      if (config.moduleConfig.mqtt.username) mqttUsername.value = config.moduleConfig.mqtt.username;
      // Pre-fill password from the user's own uploaded config so it's preserved on export
      if (config.moduleConfig.mqtt.password) mqttPassword.value = config.moduleConfig.mqtt.password;
      if (config.moduleConfig.mqtt.root) {
        // Try to extract city from root topic
        const rootMatch = config.moduleConfig.mqtt.root.match(/^msh\/US\/AZ\/(.+)$/);
        if (rootMatch) mqttCity.value = rootMatch[1];
      }
      mqttProxyToggle.checked = config.moduleConfig.mqtt.proxyToClientEnabled || false;
      mqttMapReportToggle.checked = config.moduleConfig.mqtt.mapReportingEnabled || false;
      if (config.moduleConfig.mqtt.mapReportSettings && config.moduleConfig.mqtt.mapReportSettings.publishIntervalSecs) {
        mqttMapInterval.value = config.moduleConfig.mqtt.mapReportSettings.publishIntervalSecs;
      }
      mqttMapIntervalRow.style.display = mqttMapReportToggle.checked ? 'grid' : 'none';
    }

    // Show bottom action bar
    bottomActionBar.style.display = 'block';
    autoFixBtn.disabled = false;

    // Update button text
    if (isNewNodeConfig) {
      autoFixBtn.innerHTML =
        '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg> ' +
        'Download Config (.yaml)';
    } else {
      const formatLabel = {
        android: '.cfg',
        backup: '.cfg',
        json: '.json',
        yaml: '.yaml'
      }[config.source] || '.yaml';
      autoFixBtn.innerHTML =
        '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z"/></svg> ' +
        'Auto-Fix &amp; Download Config (' + escapeHtml(formatLabel) + ')';
    }

    resultsSection.style.display = 'block';
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ---- Render: Node Info Banner ----

  function renderNodeInfo(config) {
    const existing = document.querySelector('.node-info-banner');
    if (existing) existing.remove();

    const items = [];
    if (config.longName) items.push({ label: 'Node Name', value: config.longName });
    if (config.shortName) items.push({ label: 'Short Name', value: config.shortName });
    const roleName = ConfigParser.ROLE_NAMES[config.config.device.role] || 'Unknown';
    items.push({ label: 'Role', value: roleName });
    const regionName = ConfigParser.REGION_NAMES[config.config.lora.region] || 'Unknown';
    items.push({ label: 'Region', value: regionName });
    const presetName = ConfigParser.MODEM_PRESET_NAMES[config.config.lora.modemPreset] || 'Unknown';
    items.push({ label: 'Modem Preset', value: presetName.replace(/_/g, ' ') });
    items.push({ label: 'Frequency Slot', value: String(config.config.lora.channelNum || 0) });

    if (config.firmwareVersion) {
      let fwStr = '';
      const fw = config.firmwareVersion;
      if (typeof fw === 'number' && fw > 0) {
        const major = Math.floor(fw / 10000);
        const minor = Math.floor((fw % 10000) / 100);
        const patch = fw % 100;
        fwStr = `${major}.${minor}.${patch}`;
      } else if (typeof fw === 'string') {
        fwStr = fw;
      }
      if (fwStr) items.push({ label: 'Firmware', value: fwStr });
    }

    if (items.length === 0) return;

    const banner = document.createElement('div');
    banner.className = 'node-info-banner';
    banner.innerHTML = items.map(it =>
      `<div class="node-info-item"><span class="label">${escapeHtml(it.label)}</span><span class="value">${escapeHtml(it.value)}</span></div>`
    ).join('');

    resultsSection.insertBefore(banner, healthScoreContainer);
  }

  // ---- Render: Health Score ----

  function renderHealthScore(report) {
    const { score, total, passed, failed, warnings } = report;
    const circumference = 2 * Math.PI * 56;
    const offset = circumference - (score / 100) * circumference;

    let color, label;
    if (score >= 90) { color = 'var(--success)'; label = 'Excellent'; }
    else if (score >= 70) { color = 'var(--warning)'; label = 'Good'; }
    else if (score >= 50) { color = 'var(--accent-orange)'; label = 'Needs Work'; }
    else { color = 'var(--error)'; label = 'Needs Attention'; }

    healthScoreContainer.innerHTML = `
      <div class="health-ring">
        <svg width="140" height="140" viewBox="0 0 140 140">
          <circle class="health-ring-bg" cx="70" cy="70" r="56"/>
          <circle class="health-ring-fill" cx="70" cy="70" r="56"
            stroke="${color}"
            stroke-dasharray="${circumference}"
            stroke-dashoffset="${offset}"/>
        </svg>
        <div class="health-score-text" style="color: ${escapeHtml(color)}">${escapeHtml(String(score))}</div>
      </div>
      <span class="health-label" style="color: ${escapeHtml(color)}">${escapeHtml(label)}</span>
      <p class="health-summary">${escapeHtml(String(passed))} passed, ${escapeHtml(String(failed))} failed, ${escapeHtml(String(warnings))} warnings out of ${escapeHtml(String(total))} checks</p>
    `;
  }

  // ---- Render: Results ----

  function renderResults(report) {
    resultsContainer.innerHTML = '';

    for (const category of report.categories) {
      const catEl = document.createElement('div');
      catEl.className = 'result-category';

      const counts = { pass: 0, fail: 0, warn: 0, info: 0 };
      category.checks.forEach(c => counts[c.status]++);

      let badgeClass, badgeText;
      if (counts.fail > 0) {
        badgeClass = 'badge-fail';
        badgeText = `${counts.fail} issue${counts.fail > 1 ? 's' : ''}`;
      } else if (counts.warn > 0) {
        badgeClass = 'badge-warn';
        badgeText = `${counts.warn} warning${counts.warn > 1 ? 's' : ''}`;
      } else if (counts.pass > 0) {
        badgeClass = 'badge-pass';
        badgeText = 'All good';
      } else {
        badgeClass = 'badge-info';
        badgeText = 'Info';
      }

      const startExpanded = counts.fail > 0 || counts.warn > 0;

      catEl.innerHTML = `
        <div class="category-header ${startExpanded ? 'expanded' : ''}">
          <div class="category-header-left">
            <span class="category-icon">${escapeHtml(category.icon)}</span>
            <span class="category-title">${escapeHtml(category.title)}</span>
          </div>
          <div style="display:flex;align-items:center;gap:0.5rem;">
            <span class="category-badge ${escapeHtml(badgeClass)}">${escapeHtml(badgeText)}</span>
            <span class="category-chevron">\u25BC</span>
          </div>
        </div>
        <div class="category-body ${startExpanded ? 'visible' : ''}"></div>
      `;

      const header = catEl.querySelector('.category-header');
      const body = catEl.querySelector('.category-body');

      header.addEventListener('click', () => {
        header.classList.toggle('expanded');
        body.classList.toggle('visible');
      });

      for (const check of category.checks) {
        body.appendChild(renderCheckItem(check));
      }

      if (category.title === 'MQTT Configuration' && mqttConfigBody) {
        body.appendChild(mqttConfigBody);
      }

      resultsContainer.appendChild(catEl);
    }
  }

  function renderCheckItem(check) {
    const el = document.createElement('div');
    el.className = 'check-item';

    const iconSymbol = {
      pass: '\u2713', fail: '\u2717', warn: '!', info: 'i'
    }[check.status];

    let valuesHtml = '';
    if (check.current != null && check.expected != null) {
      const isMatch = check.status === 'pass';
      valuesHtml = `
        <div class="check-values">
          <span class="check-value-current ${isMatch ? 'match' : ''}">Current: ${escapeHtml(check.current)}</span>
          <span class="check-value-expected">Expected: ${escapeHtml(check.expected)}</span>
        </div>
      `;
    } else if (check.current != null) {
      const isMatch = check.status === 'pass';
      valuesHtml = `
        <div class="check-values">
          <span class="check-value-current ${isMatch ? 'match' : ''}">${escapeHtml(check.current)}</span>
        </div>
      `;
    }

    // Editable input for user customization — uses appropriate control type
    let editHtml = '';
    if (check.settingKey && check.expected != null) {
      const currentOverride = userOverrides[check.settingKey] || '';
      const settingMeta = SETTING_TYPES[check.settingKey];
      const inputType = settingMeta ? settingMeta.type : 'text';

      if (inputType === 'select') {
        // Dropdown for enum values
        const options = settingMeta.options || [];
        let optionsHtml = '<option value="">Use recommended</option>';
        for (const opt of options) {
          const selected = currentOverride === opt.value ? ' selected' : '';
          optionsHtml += `<option value="${escapeHtml(opt.value)}"${selected}>${escapeHtml(opt.label)}</option>`;
        }
        editHtml = `
          <div class="check-values" style="margin-top:0.3rem;">
            <label class="check-edit-label">Your value:</label>
            <select class="check-edit-input check-edit-select"
              data-setting-key="${escapeHtml(check.settingKey)}">
              ${optionsHtml}
            </select>
          </div>
        `;
      } else if (inputType === 'toggle') {
        // Toggle switch for boolean values
        const isChecked = currentOverride === 'true' || currentOverride === 'Enabled' || currentOverride === 'ON';
        editHtml = `
          <div class="check-values" style="margin-top:0.3rem;">
            <label class="check-edit-label">Your value:</label>
            <label class="toggle-label compact check-edit-toggle">
              <input type="checkbox" class="check-edit-input"
                data-setting-key="${escapeHtml(check.settingKey)}"
                data-input-type="toggle"
                ${isChecked ? 'checked' : ''}>
              <span class="toggle-switch"></span>
              <span class="toggle-text">${isChecked ? 'Enabled' : 'Disabled'}</span>
            </label>
          </div>
        `;
      } else if (inputType === 'time') {
        // Time input with human-readable display
        const placeholderSeconds = check.expected || '';
        // Extract just the numeric seconds from expected (which may have format like "3600 (1.0h)")
        const expectedNum = parseInt(String(check.expected).replace(/[^0-9]/g, '')) || 0;
        const humanReadable = expectedNum > 0 ? formatSeconds(expectedNum) : '';
        const currentValHint = currentOverride ? formatSeconds(parseTimeInput(currentOverride)) : '';
        editHtml = `
          <div class="check-values" style="margin-top:0.3rem;">
            <label class="check-edit-label">Your value:</label>
            <div class="time-input-group">
              <input type="text" class="check-edit-input check-edit-time"
                data-setting-key="${escapeHtml(check.settingKey)}"
                data-input-type="time"
                placeholder="${escapeHtml(humanReadable || placeholderSeconds)}"
                value="${escapeHtml(currentOverride)}"
              >
              <span class="time-hint">${currentValHint ? escapeHtml(currentValHint) : 'e.g., 12h, 30m, 1.5d'}</span>
            </div>
          </div>
        `;
      } else {
        // Default text input
        editHtml = `
          <div class="check-values" style="margin-top:0.3rem;">
            <label class="check-edit-label">Your value:</label>
            <input type="text" class="check-edit-input"
              data-setting-key="${escapeHtml(check.settingKey)}"
              placeholder="${escapeHtml(check.expected)}"
              value="${escapeHtml(currentOverride)}"
            >
          </div>
        `;
      }
    }

    let fixHtml = '';
    if (check.status !== 'pass' && (check.why || (check.fix && check.fix.length > 0))) {
      fixHtml = `<details class="fix-details"><summary>How to fix</summary>`;
      if (check.why) {
        fixHtml += `<p class="fix-why">${escapeHtml(check.why)}</p>`;
      }
      if (check.fix && check.fix.length > 0) {
        fixHtml += '<ol class="fix-steps">' +
          check.fix.map(s => `<li>${escapeHtml(s)}</li>`).join('') +
          '</ol>';
      }
      fixHtml += '</details>';
    }

    el.innerHTML = `
      <div class="check-icon ${check.status}">${iconSymbol}</div>
      <div class="check-content">
        <div class="check-title">${escapeHtml(check.title)}</div>
        <div class="check-detail">${escapeHtml(check.detail)}</div>
        ${valuesHtml}
        ${editHtml}
        ${fixHtml}
      </div>
    `;

    // Bind change handlers for editable inputs
    const input = el.querySelector('.check-edit-input');
    if (input) {
      const inputType = input.dataset.inputType;

      if (inputType === 'toggle') {
        input.addEventListener('change', (e) => {
          const key = e.target.dataset.settingKey;
          const toggleText = el.querySelector('.toggle-text');
          if (e.target.checked) {
            userOverrides[key] = 'true';
            if (toggleText) toggleText.textContent = 'Enabled';
          } else {
            userOverrides[key] = 'false';
            if (toggleText) toggleText.textContent = 'Disabled';
          }
        });
      } else if (inputType === 'time') {
        input.addEventListener('change', (e) => {
          const key = e.target.dataset.settingKey;
          const raw = e.target.value.trim();
          if (!raw) {
            delete userOverrides[key];
            const hint = el.querySelector('.time-hint');
            if (hint) hint.textContent = 'e.g., 12h, 30m, 1.5d';
            return;
          }
          const seconds = parseTimeInput(raw);
          if (!isNaN(seconds) && seconds >= 0) {
            userOverrides[key] = String(seconds);
            const hint = el.querySelector('.time-hint');
            if (hint) hint.textContent = formatSeconds(seconds);
          }
        });
      } else {
        input.addEventListener('change', (e) => {
          const key = e.target.dataset.settingKey;
          const val = (e.target.tagName === 'SELECT') ? e.target.value : e.target.value.trim();
          if (val) {
            userOverrides[key] = val;
          } else {
            delete userOverrides[key];
          }
        });
      }
    }

    return el;
  }

  // ---- Report Text Generation ----

  function generateReportText(report) {
    const lines = [];
    lines.push('Arizona Meshtastic Config Check Report');
    lines.push('=' .repeat(42));
    lines.push(`Score: ${report.score}/100 (${report.passed} passed, ${report.failed} failed, ${report.warnings} warnings)`);
    lines.push('');

    for (const cat of report.categories) {
      lines.push(`--- ${cat.icon} ${cat.title} ---`);
      for (const check of cat.checks) {
        const icon = { pass: '[OK]', fail: '[FAIL]', warn: '[WARN]', info: '[INFO]' }[check.status];
        lines.push(`  ${icon} ${check.title}`);
        if (check.current != null) lines.push(`       Current:  ${check.current}`);
        if (check.expected != null) lines.push(`       Expected: ${check.expected}`);
        if (check.status !== 'pass' && check.fix) {
          lines.push('       Fix:');
          check.fix.forEach((step, i) => lines.push(`         ${i + 1}. ${step}`));
        }
      }
      lines.push('');
    }

    lines.push('Generated by Arizona Meshtastic Config Checker - config.azmsh.net');
    return lines.join('\n');
  }

  // ---- Helpers ----

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }

  function downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ---- Init ----

  if (window !== window.parent) {
    document.body.classList.add('embedded');
  }

  async function fetchLatestFirmware() {
    try {
      const res = await fetch('https://api.github.com/repos/meshtastic/firmware/releases/latest');
      if (res.ok) {
        const data = await res.json();
        const tag = data.tag_name.replace(/^v/, '');
        const parts = tag.split('.');
        if (parts.length >= 3) {
          const numericMin = (parseInt(parts[0]) || 0) * 10000 +
                             (parseInt(parts[1]) || 0) * 100 +
                             (parseInt(parts[2]) || 0);
          ConfigChecker.setLatestFirmware(tag, numericMin);
        }
      }
    } catch (err) {
      console.warn('Failed to fetch latest firmware:', err);
      recordDiag({ step: STEPS.FIRMWARE_CHECK, error: err });
    }
  }

  fetchLatestFirmware();
