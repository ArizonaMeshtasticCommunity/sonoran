/**
 * channel-url.js — encode/decode Meshtastic shareable channel URLs.
 *
 * Background (issue #20): the Android .cfg export is a `DeviceProfile`
 * protobuf, and DeviceProfile has NO `channels` field. The channels live in
 * `channel_url` — a string of the form:
 *
 *     https://meshtastic.org/e/#<base64url(ChannelSet protobuf)>
 *
 * where the base64 uses the URL-safe alphabet (`-`/`_`) with `=` padding
 * stripped (matching meshtastic-python node.getURL()/setURL()).
 *
 * ChannelSet only carries `settings` (repeated ChannelSettings) and an
 * optional `loraConfig`; it has no per-channel role/index. Convention: the
 * first settings entry is the PRIMARY channel (role 1), the rest are SECONDARY
 * (role 2). We preserve that on decode and re-apply it on encode.
 *
 * This module is browser + Node compatible. It expects a `protobuf` (protobuf.js)
 * global and a `MeshtasticProto` JSON descriptor — both already loaded by the
 * app and polyfilled by the test harness.
 */

const URL_PREFIX = 'https://meshtastic.org/e/#';

function getProtoEnv() {
  const pb = (typeof protobuf !== 'undefined') ? protobuf
    : (typeof window !== 'undefined' ? window.protobuf : undefined);
  const desc = (typeof window !== 'undefined' && window.MeshtasticProto)
    ? window.MeshtasticProto
    : (typeof MeshtasticProto !== 'undefined' ? MeshtasticProto : undefined);
  if (!pb || !desc) {
    throw new Error('protobuf runtime / MeshtasticProto descriptor not available');
  }
  return { pb, desc };
}

// ---- base64url <-> bytes (no Buffer/atob assumptions; works in both envs) ----

const B64_STD =
  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

function bytesToBase64Url(bytes) {
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const b1 = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const b2 = i + 2 < bytes.length ? bytes[i + 2] : 0;
    const triplet = (b0 << 16) | (b1 << 8) | b2;
    out += B64_STD[(triplet >> 18) & 0x3f];
    out += B64_STD[(triplet >> 12) & 0x3f];
    out += i + 1 < bytes.length ? B64_STD[(triplet >> 6) & 0x3f] : '';
    out += i + 2 < bytes.length ? B64_STD[triplet & 0x3f] : '';
  }
  // URL-safe, padding stripped.
  return out.replace(/\+/g, '-').replace(/\//g, '_');
}

function base64UrlToBytes(b64url) {
  let s = String(b64url).replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  const lookup = new Int16Array(256).fill(-1);
  for (let i = 0; i < B64_STD.length; i++) lookup[B64_STD.charCodeAt(i)] = i;

  const clean = s.replace(/=+$/, '');
  const byteLen = Math.floor((clean.length * 6) / 8);
  const bytes = new Uint8Array(byteLen);
  let acc = 0, accBits = 0, oi = 0;
  for (let i = 0; i < clean.length; i++) {
    const v = lookup[clean.charCodeAt(i)];
    if (v < 0) continue;
    acc = (acc << 6) | v;
    accBits += 6;
    if (accBits >= 8) {
      accBits -= 8;
      bytes[oi++] = (acc >> accBits) & 0xff;
    }
  }
  return bytes;
}

/**
 * Decode a channel URL into an array of normalized channel objects.
 * Returns [] if the URL is empty or cannot be parsed.
 *
 * Each returned channel: { index, name, psk (Uint8Array), uplinkEnabled,
 * downlinkEnabled, role } matching the parser's normalized channel shape.
 */
export function decodeChannelUrl(url) {
  if (!url || typeof url !== 'string') return [];
  let payload = url.trim();
  const hashIdx = payload.indexOf('#');
  if (hashIdx >= 0) {
    payload = payload.slice(hashIdx + 1);
  } else if (/^https?:/i.test(payload)) {
    // A URL without a fragment carries no channel data.
    return [];
  }
  if (!payload) return [];

  let bytes;
  try {
    bytes = base64UrlToBytes(payload);
  } catch (e) {
    return [];
  }
  if (!bytes || bytes.length === 0) return [];

  const { pb, desc } = getProtoEnv();
  const root = pb.Root.fromJSON(desc);
  const ChannelSet = root.lookupType('meshtastic.ChannelSet');

  let decoded;
  try {
    decoded = ChannelSet.decode(bytes);
  } catch (e) {
    return [];
  }

  const settings = (decoded.settings && Array.isArray(decoded.settings))
    ? decoded.settings
    : [];

  return settings.map((s, i) => ({
    index: i,
    name: s.name || '',
    psk: s.psk != null ? s.psk : new Uint8Array([1]),
    uplinkEnabled: !!s.uplinkEnabled,
    downlinkEnabled: !!s.downlinkEnabled,
    // ChannelSet has no role; first entry is primary (1), rest secondary (2).
    role: i === 0 ? 1 : 2
  }));
}

/**
 * Encode an array of normalized channel objects into a channel URL.
 * Returns '' when there are no channels.
 *
 * @param {Array} channels - normalized channels (name, psk, uplink/downlink)
 * @param {Object} [loraConfig] - optional { modemPreset, channelNum, region, usePreset }
 */
export function encodeChannelUrl(channels, loraConfig) {
  const list = (channels || []).filter(Boolean);
  if (list.length === 0) return '';

  const { pb, desc } = getProtoEnv();
  const root = pb.Root.fromJSON(desc);
  const ChannelSet = root.lookupType('meshtastic.ChannelSet');

  const settings = list.map(ch => {
    let pskBytes;
    if (ch.psk instanceof Uint8Array) {
      pskBytes = ch.psk;
    } else if (Array.isArray(ch.psk)) {
      pskBytes = new Uint8Array(ch.psk);
    } else if (typeof ch.psk === 'string' && ch.psk.length > 0) {
      if (ch.psk === 'AQ==' || ch.psk === 'AQ') {
        pskBytes = new Uint8Array([1]);
      } else {
        try {
          pskBytes = base64UrlToBytes(ch.psk);
        } catch (e) {
          pskBytes = new Uint8Array([1]);
        }
      }
    } else if (ch.psk && typeof ch.psk === 'object') {
      // A Uint8Array that has been through JSON.parse(JSON.stringify(...)) comes
      // back as a plain object { "0": 1, "1": 2, ... }. The fixer deep-clones
      // configs that way, so reconstruct the byte array from numeric keys.
      const keys = Object.keys(ch.psk).filter(k => /^\d+$/.test(k));
      if (keys.length > 0) {
        const arr = new Uint8Array(keys.length);
        for (const k of keys) arr[Number(k)] = ch.psk[k] & 0xff;
        pskBytes = arr;
      } else {
        pskBytes = new Uint8Array([1]);
      }
    } else {
      pskBytes = new Uint8Array([1]); // default key
    }

    return {
      name: ch.name || '',
      psk: pskBytes,
      uplinkEnabled: !!ch.uplinkEnabled,
      downlinkEnabled: !!ch.downlinkEnabled
    };
  });

  const obj = { settings };
  if (loraConfig && typeof loraConfig === 'object') {
    obj.loraConfig = {
      usePreset: loraConfig.usePreset != null ? !!loraConfig.usePreset : true,
      modemPreset: loraConfig.modemPreset || 0,
      channelNum: loraConfig.channelNum || 0,
      region: loraConfig.region || 0
    };
  }

  const errMsg = ChannelSet.verify(obj);
  if (errMsg) throw new Error('ChannelSet verification failed: ' + errMsg);

  const message = ChannelSet.create(obj);
  const bytes = ChannelSet.encode(message).finish();
  return URL_PREFIX + bytesToBase64Url(bytes);
}

export const ChannelUrl = { decodeChannelUrl, encodeChannelUrl, URL_PREFIX };
